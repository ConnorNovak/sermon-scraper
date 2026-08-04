"""
Crawl a Subsplash church site, download sermon mp3s, and tag them with
metadata (title, scripture, speaker, date, cover art) pulled from the
site's own JSON API.
"""

import json
import logging
import re
import shutil
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

import plac  # type: ignore [import-untyped]
import requests
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TDRC, TCON, APIC
from playwright.sync_api import sync_playwright
from pydantic import BaseModel
from tqdm import tqdm

from .model import MediaItem, MediaSeries

_logger = logging.getLogger(__name__)

# --- Config -----------------------------------------------------------------

OUTPUT_DIR = Path("./data")
#: The targeted subsplash organization slug
ORG_SLUG = "calvarychapeltherock"
APP_KEY = "6QVR5X"

API_BASE = "https://core.subsplash.com"
REQUEST_DELAY_SECONDS = 0.3
PAGE_SIZE = 50


# --- UI ----------------------------------------------------------------------

output_dir_annotation = plac.Annotation(
    help="directory to write series/episodes into",
    kind="option",
    type=Path,
)


def prompt_choice(choices: list[str]) -> int:
    """Prompt the user to choose from a list of choices, returning the index of the selected choice.

    :param choices: A list of strings representing the choices.
    :return: The index of the selected choice in the choices list.
    :raises SystemExit: If the user chooses to quit by entering 'q'.
    """
    while True:
        buf = len(str(len(choices)))
        for i, choice in enumerate(choices):
            print(f"{i + 1:{buf}}) {choice}")
        selection = input("Select entry by number [1-N|q]: ")
        if selection.lower() == "q":
            raise sys.exit("User chose to quit.")
        try:
            index = int(selection) - 1
            if 0 <= index < len(choices):
                return index
            else:
                print(
                    f"Invalid choice. Please enter a number between 1 and {len(choices)}."
                )
        except ValueError:
            print("Invalid input. Please enter a number.")


def prompt_yes_no(question: str) -> bool:
    """Prompt the user with a yes/no question and return True for yes, False for no.

    :param question: The question to ask the user.
    :return: True if the user answered yes, False if the user answered no.
    """
    while True:
        answer = input(f"{question} [y|n|q]: ").strip().lower()
        if answer == "q":
            raise SystemExit("User chose to quit.")
        if answer in ("y", "yes"):
            return True
        elif answer in ("n", "no"):
            return False
        else:
            print("Invalid input. Please enter 'y' or 'n'.")


# --- Auth --------------------------------------------------------------------


def get_guest_token() -> str:
    """Load a real page in a headless browser and pull the guest bearer
    token subsplash's frontend mints for itself out of localStorage.
    Avoids reverse-engineering the token-mint POST body (client_secret
    lives in a minified JS bundle and isn't worth chasing for a one-off
    script)."""
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
    rsp = session.get(url, params=params)
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


def list_episodes(session: requests.Session, series_id: str):
    url = f"{API_BASE}/media/v1/media-items"
    params = {
        "filter[media_series]": series_id,
        "filter[status]": "published",
        "include": "images,audio.audio-outputs,video.video-outputs",
        "page[size]": PAGE_SIZE,
        "sort": "-position",
    }
    return list(paginate(session, url, params, "media-items"))


# --- Extraction helpers -----------------------------------------------------


def slugify(text: str) -> str:
    """Convert a string into a slug suitable for filenames or URLs."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def get_mp3_url(episode: dict) -> str | None:
    """Return the url of the corresponding mp3 file, or None if not available."""
    # Check the _embedded dict for audio
    url: str | None = None
    try:
        url = episode["_embedded"]["audio"]["_embedded"]["audio-outputs"][0]["_links"][
            "related"
        ]["href"]
        if "external_audio_url" in episode:
            _logger.warning(
                "%s has both embedded audio and external_audio_url, using embedded audio",
                episode.get("id"),
            )
    except KeyError, IndexError:
        _logger.warning(
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
    resp = session.get(url, stream=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    with (
        open(dest, "wb") as f,
        tqdm(
            total=total, unit="B", unit_scale=True, unit_divisor=1024, desc=dest.name
        ) as bar,
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
                    resp = session.get(image_url)
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
    episodes = list_episodes(session, body["id"])
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


def write_series_list(output_file: Path) -> None:
    """Write the list of available series to a text file."""
    print("fetching guest token...")
    token = get_guest_token()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    print("listing series...")
    series_list = list_all_series(session)
    print(f"found {len(series_list)} series")

    duplicate_titles: dict[str, int] = {}
    for series in series_list:
        title = series["title"]
        if title in duplicate_titles:
            duplicate_titles[title] += 1
        else:
            duplicate_titles[title] = 1

    print("duplicate series titles:")
    for title, count in duplicate_titles.items():
        if count > 1:
            print(f"  {title}: {count} duplicates")

    def media_items_count(series: dict) -> int:
        return series.get("media_items_count", 0)

    with open("series.txt", "w") as f:
        for series in sorted(series_list, key=media_items_count, reverse=True):
            f.write(f"{series['title']} ({series['media_items_count']} episodes)\n")


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

    _logger.debug(
        "audio: %s, video: %s, images: %s, nocache: %s", audio, video, images, nocache
    )
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

        episodes = list_episodes(session, series["id"])
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


@plac.annotations(
    series_slug=plac.Annotation(
        "series slug to download (e.g. 'matthew')", "positional"
    ),
    output_dir=output_dir_annotation,
)
def download_series(
    series_slug: str,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """Download a single series by its slug (e.g. "matthew")."""
    if not output_dir.exists() and not prompt_yes_no(
        f"Output directory '{output_dir}' does not exist. Create it?"
    ):
        raise RuntimeError(f"Output directory '{output_dir}' does not exist.")
    output_dir.mkdir(parents=True, exist_ok=True)

    token = get_guest_token()
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    series_list = list_all_series(session)
    series_slugs = [s.get("slug", "") for s in series_list]
    matches = get_close_matches(series_slug, series_slugs, n=3, cutoff=0.6)
    if len(matches) > 1:
        _logger.info("%d series match slug '%s':", len(matches), series_slug)
        match = matches[prompt_choice(matches)]
    elif len(matches) == 0:
        raise RuntimeError(f"No series match slug '{series_slug}'")
    else:
        match = matches[0]
    idx = series_slugs.index(match)
    series = series_list[idx]
    series_dir = output_dir / slugify(f"{series['title']}-{series['short_code']}")
    episodes = list_episodes(session, series["id"])
    _logger.info("found series: '%s' (%d)", series["title"], len(episodes))
    for episode in episodes:
        process_episode(
            session,
            series["title"],
            episode,
            series_dir,
            want_audio=True,
            want_video=True,
            want_images=True,
            nocache=False,
        )
    return


class Scripture(BaseModel):
    """Schema for a parsed scripture reference."""

    book: str
    chapter: str
    start_verse: str
    end_verse: str


class Speaker(BaseModel):
    """Schema for a parsed speaker name."""

    title: str | None
    first_name: str
    last_name: str


def _parse_scripture(scripture: str) -> Scripture:
    """Parse a scripture string into its components: book, chapter, start verse, end verse.

    Example: "1 Samuel 14:1-23"

    :param scripture: Scripture string in the format "Book Chapter:StartVerse-EndVerse"
    :return: Scripture dataclass parsed from the string
    """
    match = re.match(
        r"(?P<book>[A-Za-z0-9 ]+) (?P<chapter>\d+):(?P<start_verse>\d+)(-(?P<end_verse>\d+))?",
        scripture,
    )

    if not match:
        raise ValueError(f"Invalid scripture format: '{scripture}'")

    return Scripture(
        book=match.group("book").replace(" ", "-"),
        chapter=match.group("chapter"),
        start_verse=match.group("start_verse"),
        end_verse=match.group("end_verse") or match.group("start_verse"),
    )


def _parse_speaker(speaker: str) -> Speaker:
    """Parse a speaker string into its components: title, first name, last name.

    Example: "Pastor John Doe"

    :param speaker: Speaker string in the format "[Title] FirstName LastName"
    :return: Speaker dataclass parsed from the string
    """
    # Catch known bad data and correct it
    if speaker == "Passss Reinman":
        speaker = "Pastor Ross Reinman"

    parts = speaker.split()
    if len(parts) < 2:
        raise ValueError(f"Invalid speaker format: '{speaker}'")

    title = parts[0] if len(parts) > 2 else None
    first_name = parts[-2] if title else parts[0]
    last_name = parts[-1]

    return Speaker(title=title, first_name=first_name, last_name=last_name)


def _parse_title(title: str) -> str:
    """Parse a title string

    Currently per Spencer's format, we don't need to modify the title.

    :param title: Title string
    :return: Slugified title string
    """
    return title


@plac.annotations(
    target_dir=plac.Annotation(
        "Directory of downloaded sermons to convert and rename.",
        type=Path,
    ),
    dry_run=plac.Annotation(
        "Print the proposed renames without actually renaming files.", kind="flag"
    ),
    output_dir=output_dir_annotation,
    replace=plac.Annotation(
        "Replace the files in the output directory instead of copying them.", kind="flag"
    )
)
def rename_files(
    target_dir: Path,
    dry_run: bool = False,
    output_dir: Path | None = None,
    replace: bool = False,
) -> None:
    """Rename the downloaded .mp3 files to Spencer's format using the related .json file.

    Spencer's format:
        [BOOK]_[CHAPTER]([START_VERSE]-[END_VERSE])_[PREACHER]_[YEAR]-[MONTH]-[DAY]_[SERMON_TITLE].mp3

    :param target_dir: Directory containing the downloaded sermon files.
    :param dry_run: If True, print the proposed renames without actually renaming files.
    :param output_dir: Optional directory to move the renamed files into. If not provided, files will be renamed in place.
    :param copy: If True, copy the files to the output directory instead of moving them.
    """
    if not target_dir.exists():
        raise FileNotFoundError(f"Target directory '{target_dir}' does not exist.")
    if output_dir is None:
        output_dir = target_dir

    if not output_dir.exists():
        if not prompt_yes_no(
            f"Output directory '{output_dir}' does not exist. Create it?"
        ):
            raise RuntimeError(f"Output directory '{output_dir}' does not exist.")

    output_dir.mkdir(parents=True, exist_ok=True)

    file_plan: list[tuple[Path, Path]] = []
    for slug in set(f.stem for f in target_dir.glob("*.mp3")):
        json_file = target_dir / f"{slug}.json"
        mp3_file = target_dir / f"{slug}.mp3"
        with open(json_file, "r") as f:
            metadata = json.load(f)

        scripture = _parse_scripture(metadata["scripture"])
        speaker = _parse_speaker(metadata["speaker"])
        date = datetime.fromisoformat(metadata["date"])
        title = _parse_title(metadata["title"])

        filename = f"{scripture.book}_{scripture.chapter}({scripture.start_verse}-{scripture.end_verse})_{speaker.first_name}_{date.year}-{date.month:02d}-{date.day:02d}_{title}.mp3"
        file_plan.append((mp3_file, output_dir / filename))

    if dry_run:
        col_1_len = max(len(src.name) for src, dst in file_plan)
        col_2_len = max(len(dst.name) for src, dst in file_plan)
        print("Dry run: proposed renames:")
        print(f"--{'-' * col_1_len}---{'-' * col_2_len}--")
        print(f"| {'Current Name':{col_1_len}} | New Name{' ' * (col_2_len - 8)} |")
        print(f"--{'-' * col_1_len}---{'-' * col_2_len}--")
        for src, dst in file_plan:
            print(f"| {src.name:{col_1_len}} | {dst.name:{col_2_len}} |")
        print(f"--{'-' * col_1_len}---{'-' * col_2_len}--")
    else:
        for old_path, new_path in file_plan:
            if not replace:
                shutil.copy2(old_path, new_path)
            else:
                old_path.rename(new_path)
            print(f"Renamed: {old_path} | {new_path}")


@plac.annotations(
    target_dir=plac.Annotation(
        "Directory of downloaded sermons to convert and rename.",
        type=Path,
    ),
    dry_run=plac.Annotation(
        "Print the proposed renames without actually renaming files.", kind="flag"
    ),
    output_dir=output_dir_annotation,
    replace=plac.Annotation(
        "Replace the files in the output directory instead of copying them.", kind="flag"
    )
)
def generate_drew_csv(
    target_dir: Path,
    dry_run: bool = False,
    output_dir: Path | None = None,
    replace: bool = False,
) -> None:
    """Generate a CSV mapping of .mp3 files to metadata compliant with Drew's desired format.

    Drew's format:
        file, book, chapter, [BOOK]_[CHAPTER]([START_VERSE]-[END_VERSE])_[PREACHER]_[YEAR]-[MONTH]-[DAY]_[SERMON_TITLE].mp3

    :param target_dir: Directory containing the downloaded sermon files.
    :param dry_run: If True, print the proposed renames without actually renaming files.
    :param output_dir: Optional directory to move the renamed files into. If not provided, files will be renamed in place.
    :param copy: If True, copy the files to the output directory instead of moving them.
    """
    if not target_dir.exists():
        raise FileNotFoundError(f"Target directory '{target_dir}' does not exist.")
    if output_dir is None:
        output_dir = target_dir

    if not output_dir.exists():
        if not prompt_yes_no(
            f"Output directory '{output_dir}' does not exist. Create it?"
        ):
            raise RuntimeError(f"Output directory '{output_dir}' does not exist.")

    output_dir.mkdir(parents=True, exist_ok=True)

    file_plan: list[tuple[Path, Path]] = []
    for slug in set(f.stem for f in target_dir.glob("*.mp3")):
        json_file = target_dir / f"{slug}.json"
        mp3_file = target_dir / f"{slug}.mp3"
        with open(json_file, "r") as f:
            metadata = json.load(f)

        scripture = _parse_scripture(metadata["scripture"])
        speaker = _parse_speaker(metadata["speaker"])
        date = datetime.fromisoformat(metadata["date"])
        title = _parse_title(metadata["title"])

        filename = f"{scripture.book}_{scripture.chapter}({scripture.start_verse}-{scripture.end_verse})_{speaker.first_name}_{date.year}-{date.month:02d}-{date.day:02d}_{title}.mp3"
        file_plan.append((mp3_file, output_dir / filename))

    if dry_run:
        col_1_len = max(len(src.name) for src, dst in file_plan)
        col_2_len = max(len(dst.name) for src, dst in file_plan)
        print("Dry run: proposed renames:")
        print(f"--{'-' * col_1_len}---{'-' * col_2_len}--")
        print(f"| {'Current Name':{col_1_len}} | New Name{' ' * (col_2_len - 8)} |")
        print(f"--{'-' * col_1_len}---{'-' * col_2_len}--")
        for src, dst in file_plan:
            print(f"| {src.name:{col_1_len}} | {dst.name:{col_2_len}} |")
        print(f"--{'-' * col_1_len}---{'-' * col_2_len}--")
    else:
        for old_path, new_path in file_plan:
            if not replace:
                shutil.copy2(old_path, new_path)
            else:
                old_path.rename(new_path)
            print(f"Renamed: {old_path} | {new_path}")


if __name__ == "__main__":
    # plac.call(main)
    plac.call(download_series)
    # plac.call(rename_files)
