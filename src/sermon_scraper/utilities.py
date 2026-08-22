import re
from pathlib import Path

import requests


def slugify(text: str) -> str:
    """Convert a string into a slug suitable for filenames or URLs."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


# --- Resource Retrieval Methods -------------------------------------------------------------------


def retrieve_resource_length_in_bytes(url: str, session: requests.Session | None = None) -> int:
    """Retrieve the length of a resource in bytes from its URL.

    :param url: The URL of the resource.
    :param session: Optional requests.Session to use for the request. If None, a new session will be
        created.
    :return: The length of the resource in bytes.
    """
    if session is None:
        rsp = requests.head(url, allow_redirects=True)
    else:
        rsp = session.head(url, allow_redirects=True)

    if rsp.status_code == 200:
        return int(rsp.headers.get("Content-Length", 0))
    else:
        raise ValueError(f"Failed to retrieve resource length for URL: {url}")


def retrieve_resource(url: str, destination: Path, session: requests.Session | None = None) -> None:
    """Download a resources to a file given its URL.

    :param url: The URL of the resourcee.
    :param destination: The path to save the downloaded resource.
    :param session: Optional requests.Session to use for downloading. If None, a new session will be
        created.
    """
    if session is None:
        rsp = requests.get(url, stream=True)
    else:
        rsp = session.get(url, stream=True)

    rsp.raise_for_status()
    with destination.open("wb") as f:
        for chunk in rsp.iter_content(chunk_size=8192):
            f.write(chunk)
