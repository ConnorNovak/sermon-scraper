"""
Crawl a Subsplash church site, download sermon mp3s, and tag them with
metadata (title, scripture, speaker, date, cover art) pulled from the
site's own JSON API.
"""

import json
import logging
import pdb
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pandas as pd
import plac  # type: ignore [import-untyped]
import requests
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, ID3NoHeaderError
from playwright.sync_api import sync_playwright
from tqdm import tqdm

from .constants import REQUEST_TIMEOUT
from .models import SermonResource
from .ui.cli import output_dir_annotation, prompt_yes_no
from .utilities import log_level_type, slugify

_logger = logging.getLogger(__name__)

# --- Config -----------------------------------------------------------------

OUTPUT_DIR = Path("./data")
#: The targeted subsplash organization slug
ORG_SLUG = "calvarychapeltherock"
APP_KEY = "6QVR5X"

API_BASE = "https://core.subsplash.com"
REQUEST_DELAY_SECONDS = 0.3
PAGE_SIZE = 50


# --- Auth --------------------------------------------------------------------


def get_guest_token() -> str:
    """Load a real page in a headless browser and pull the guest bearer token subsplash's frontend
    mints for itself out of localStorage.

    Avoids reverse-engineering the token-mint POST body (client_secret lives in minified JS bundle).

    :return: The guest bearer token string.
    """
    target_url = f"https://subsplash.com/u/{ORG_SLUG}/media/l/a3f0dc4-matthew"
    _logger.debug("fetching guest token from %s", target_url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # guest_token is only minted on the newer Next.js app routes
        # (/u/.../media/...), not the legacy /sermons index. "networkidle"
        # never fires here (background polling keeps the connection busy),
        # so wait for "load" plus a short settle delay instead.
        page.goto(target_url, wait_until="load")
        page.wait_for_timeout(3000)
        token = page.evaluate("() => localStorage.getItem('guest_token')")
        browser.close()

    if not token:
        raise RuntimeError("could not extract guest_token from localStorage")

    return token


# --- API -----------------------------------------------------------------


def api_get(session: requests.Session, url: str, params: dict | None = None) -> dict:
    """Wrapper around requests.get() that raises for HTTP errors and returns the JSON body."""
    rsp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    rsp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return rsp.json()


def paginate(
    session: requests.Session, url: str, params: dict, embedded_key: str
) -> Iterator[dict]:
    """Yield every item across all pages of a HAL+JSON collection."""
    next_url = url
    next_params: dict | None = params
    while next_url:
        body = api_get(session, next_url, next_params)
        yield from body.get("_embedded", {}).get(embedded_key, [])
        next_href = body.get("_links", {}).get("next", {}).get("href")
        next_url = next_href
        next_params = None  # params are already baked into next_href


def list_all_series(
    session: requests.Session,
    app_key: str = APP_KEY,
    page_size: int = PAGE_SIZE,
) -> list[dict]:
    """Use the given session to list all media series for the given app_key, yielding
    each series as a dict.

    :param session: requests.Session with Authorization header set
    :param app_key: Subsplash app key to filter series by
    :param page_size: number of series to request per page (default 50)
    :return: list of series dicts
    """
    url = f"{API_BASE}/media/v1/media-series"
    params = {"filter[app_key]": app_key, "page[size]": page_size}
    return list(paginate(session, url, params, "media-series"))


def list_series_media_items(session: requests.Session, series_id: str):
    url = f"{API_BASE}/media/v1/media-items"
    params = {
        "filter[media_series]": series_id,
        "filter[status]": "published",
        "include": "images,audio.audio-outputs,video.video-outputs",
        "page[size]": PAGE_SIZE,
        "sort": "-position",
    }
    return list(paginate(session, url, params, "media-items"))


# --- Ekklesia CSV export -----------------------------------------------------


def episode_to_resource(series_title: str, episode: dict) -> SermonResource | None:
    """Convert one Subsplash media-item into an EkklesiaResource row.

    :param series_title: Title of the series this episode belongs to.
    :param episode: Raw Subsplash media-item dict, as returned by :func:`list_series_media_items`.
    :return: The converted resource, or None if a required field (audio URL, legacy_id) is
        missing - logged as a warning rather than raising, so one bad episode doesn't kill
        the whole export.
    """
    return SermonResource(
        audio=get_mp3_url(episode),
        date=get_date(episode),
        notes=None,  # subsplash doesn't expose a distinct notes/document URL yet
        sermon_id=get_id(episode),
        sermon_title=episode["title"],
        series=series_title,
        speaker=episode.get("speaker") or "Unknown",
        video=get_video_url(episode),
    )


@plac.annotations(
    output_file=plac.Annotation("Path to write the Ekklesia-format CSV to.", type=Path),
    log_level=plac.Annotation(
        "Logging level (default INFO).",
        type=log_level_type,
    ),
)
def export_csv(output_file: Path, log_level: int = logging.INFO) -> None:
    """Crawl every Subsplash series/episode and write it out as an Ekklesia-format CSV.

    Resource-size columns (audio_size_mb, video_size_mb, notes_size_mb) are left blank -
    fill those in afterward via the TUI's 'calculate' command.

    :param output_file: Path to write the CSV to.
    """
    token = get_guest_token()
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    series_list = list_all_series(session)
    _logger.info("found %d series", len(series_list))

    resources: list[SermonResource] = []
    for series in series_list:
        if series.get("media_items_count", 0) == 0:
            _logger.debug("skipping series '%s' (no episodes)", series["title"])
            continue

        episodes = list_series_media_items(session, series["id"])
        _logger.info("series '%s': %d episodes", series["title"], len(episodes))
        for episode in episodes:
            resource = episode_to_resource(series["title"], episode)
            if resource is not None:
                resources.append(resource)

    df = pd.DataFrame([r.model_dump(mode="json") for r in resources])
    df = df[list(SermonResource.model_fields)]  # enforce the model's declared column order
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)
    _logger.info("wrote %d rows to %s", len(df), output_file)


# --- Extraction helpers -----------------------------------------------------


def get_date(episode: dict) -> datetime:
    try:
        return episode["date"]
    except KeyError as e1:
        _logger.debug("%s has no date field, using 'created_at'", episode.get("id"))
        try:
            return episode["created_at"]
        except KeyError as e2:
            _logger.error(
                "%s has no created_at field either, dropping into pdb to analyze", episode.get("id")
            )
            pdb.set_trace()
            raise e2 from e1


def get_id(episode: dict) -> int | None:
    """Extract the legacy sermon_id from a Subsplash media-item dict.

    :param episode: Raw Subsplash media-item dict, as returned by :func:`list_series_media_items`.
    :return: The legacy sermon_id, or None if not found.
    """
    try:
        return episode["legacy_id"]
    except KeyError:
        _logger.debug("%s has no legacy_id field", episode.get("id"))
        return None


def get_mp3_url(episode: dict) -> str | None:
    """Return the url of the corresponding mp3 file, or None if not available."""
    # Check the _embedded dict for audio
    url: str | None = None
    try:
        url = episode["_embedded"]["audio"]["_embedded"]["audio-outputs"][0]["_links"]["related"][
            "href"
        ]
        if "external_audio_url" in episode:
            _logger.warning(
                "%s has both embedded audio and external_audio_url, using embedded audio",
                episode.get("id"),
            )
    except KeyError, IndexError:
        _logger.debug(
            "%s has no embedded audio, falling back to external_audio_url",
            episode.get("id"),
        )
        try:
            url = episode["external_audio_url"]
        except KeyError:
            _logger.error("%s has no external_audio_url field", episode.get("id"))

    return url


def get_video_url(episode: dict) -> str | None:
    video = episode.get("_embedded", {}).get("video")
    if not video:
        return None
    outputs = video.get("_embedded", {}).get("video-outputs", [])
    if not outputs:
        return None
    return outputs[0].get("_links", {}).get("related", {}).get("href")


def get_image_url(episode: dict) -> str | None:
    """Crawl episode data to find the cover image URL, preferring the download link if available."""
    images = episode.get("_embedded", {}).get("images", [])
    if not images:
        return None
    image = images[0]
    download = image.get("_links", {}).get("download", {}).get("href")
    if download:
        return download
    ext = "png" if "png" in image.get("content_type", "") else "jpg"
    return f"https://images.subsplash.com/image.{ext}?id={image['id']}"


def get_image_extension(episode: dict) -> str:
    """Crawl episode data to determine whether the cover image is a PNG or JPG."""
    images = episode.get("_embedded", {}).get("images", [])
    if images and "png" in images[0].get("content_type", ""):
        return "png"
    return "jpg"


# --- Download + tagging ------------------------------------------------------


def download_file(session: requests.Session, url: str, dest: Path):
    resp = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    with (
        open(dest, "wb") as f,
        tqdm(total=total, unit="B", unit_scale=True, unit_divisor=1024, desc=dest.name) as bar,
    ):
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)
            bar.update(len(chunk))


def tag_mp3(
    mp3_path: Path,
    title: str,
    speaker: str,
    series: str,
    date: str,
    cover_bytes: bytes | None,
):
    """Use mutagen to write ID3 tags to the given mp3 file."""
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TIT2", [TIT2(encoding=3, text=title)])
    tags.setall("TPE1", [TPE1(encoding=3, text=speaker or "Unknown")])
    tags.setall("TALB", [TALB(encoding=3, text=series)])
    tags.setall("TDRC", [TDRC(encoding=3, text=date[:4] if date else "")])
    tags.setall("TCON", [TCON(encoding=3, text="Sermon")])
    if cover_bytes:
        tags.setall(
            "APIC",
            [
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=cover_bytes,
                )
            ],
        )
    tags.save(mp3_path)


# --- Orchestration ------------------------------------------------------------


def process_episode(
    session: requests.Session,
    series_title: str,
    body: dict,
    series_dir: Path,
    want_audio: bool,
    want_video: bool,
    want_images: bool,
    nocache: bool,
):
    title = body["title"]
    slug = body.get("slug") or slugify(title)
    mp3_path = series_dir / f"{slug}.mp3"
    mp4_path = series_dir / f"{slug}.mp4"
    image_path = series_dir / f"{slug}.{get_image_extension(body)}"
    json_path = series_dir / f"{slug}.json"

    mp3_url = get_mp3_url(body)
    video_url = get_video_url(body)
    image_url = get_image_url(body)

    def needs(path: Path) -> bool:
        return nocache or not path.exists()

    series_dir.mkdir(parents=True, exist_ok=True)

    if needs(json_path):
        json_path.write_text(
            json.dumps(
                {
                    "title": title,
                    "scripture": body.get("subtitle"),
                    "speaker": body.get("speaker"),
                    "date": body.get("date"),
                    "series": series_title,
                    "mp3_url": mp3_url,
                    "image_url": image_url,
                    "video_url": video_url,
                },
                indent=2,
            )
        )
        print(f"  wrote metadata: {title}")
    else:
        print(f"  skip json (exists): {title}")

    # Shared so audio-tagging and a standalone image download don't both
    # fetch the same cover image over the network.
    cover_bytes: bytes | None = None
    cover_fetched = False

    def fetch_cover() -> bytes | None:
        nonlocal cover_bytes, cover_fetched
        if not cover_fetched:
            cover_fetched = True
            if image_url:
                try:
                    resp = session.get(image_url, timeout=REQUEST_TIMEOUT)
                    resp.raise_for_status()
                    cover_bytes = resp.content
                except requests.RequestException as e:
                    print(f"    cover image failed: {e}")
        return cover_bytes

    if want_audio:
        if not mp3_url:
            print(f"  skip audio (no audio): {title}")
        elif not needs(mp3_path):
            print(f"  skip audio (exists): {title}")
        else:
            print(f"  downloading audio: {title}")
            download_file(session, mp3_url, mp3_path)
            tag_mp3(
                mp3_path,
                title=title,
                speaker=body.get("speaker", ""),
                series=series_title,
                date=body.get("date", ""),
                cover_bytes=fetch_cover(),
            )

    if want_video:
        if not video_url:
            print(f"  skip video (no video): {title}")
        elif not needs(mp4_path):
            print(f"  skip video (exists): {title}")
        else:
            print(f"  downloading video: {title}")
            download_file(session, video_url, mp4_path)

    if want_images:
        if not image_url:
            print(f"  skip image (no image): {title}")
        elif not needs(image_path):
            print(f"  skip image (exists): {title}")
        else:
            bytes_ = fetch_cover()
            if bytes_:
                image_path.write_bytes(bytes_)
                print(f"  downloaded image: {title}")


def process_series(
    session: requests.Session,
    body: dict,
    output_dir: Path,
    want_audio: bool,
    want_video: bool,
    want_images: bool,
    nocache: bool,
) -> None:
    series_dir = output_dir / slugify(f"{body['title']}-{body['short_code']}")
    episodes = list_series_media_items(session, body["id"])
    _logger.info("found series: '%s' (%d)", body["title"], len(episodes))
    for episode in episodes:
        process_episode(
            session,
            body["title"],
            episode,
            series_dir,
            want_audio=True,
            want_video=True,
            want_images=True,
            nocache=False,
        )
    return


@plac.annotations(
    output_dir=output_dir_annotation,
    audio=("also download mp3 audio files", "flag"),
    video=("also download mp4 video files", "flag"),
    images=("also download cover images", "flag"),
    nocache=("ignore existing files and re-download/re-write everything", "flag"),
    all=("download everything (audio, video, images)", "flag"),
)
def download_all(
    output_dir: Path = OUTPUT_DIR,
    audio: bool = False,
    video: bool = False,
    images: bool = False,
    nocache: bool = False,
    noprompt: bool = False,
    all: bool = False,
) -> None:
    """Crawl the site and write episode metadata as JSON for every sermon.

    By default only the .json sidecar is written. Pass -audio to also
    download mp3s, -video for mp4s, -images for cover art. Existing files
    are left alone unless -nocache is given, which re-downloads/re-writes
    everything.
    """
    if all:
        audio = True
        video = True
        images = True

    _logger.debug("audio: %s, video: %s, images: %s, nocache: %s", audio, video, images, nocache)
    if not noprompt and not prompt_yes_no("Continue?"):
        raise RuntimeError("user aborted")
    token = get_guest_token()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    series_list = list_all_series(session)
    _logger.info("found %d series", len(series_list))
    for series in series_list:
        if series.get("media_items_count", 0) == 0:
            _logger.info("skipping series '%s' (no episodes)", series["title"])
            continue
        series_title = series["title"]
        series_dir = output_dir / slugify(f"{series_title}-{series['short_code']}")

        episodes = list_series_media_items(session, series["id"])
        _logger.info("found series: '%s' (%d)", series_title, len(episodes))
        for episode in episodes:
            process_episode(
                session,
                series_title,
                episode,
                series_dir,
                audio,
                video,
                images,
                nocache,
            )


if __name__ == "__main__":
    plac.call(export_csv)
