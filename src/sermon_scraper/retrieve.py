"""Various data retrieval methods."""

import logging
from pathlib import Path

import requests
from tqdm import tqdm

from .constants import REQUEST_TIMEOUT
from .rate_limit import KeyedRateLimiter, RateLimitedError
from .utilities import get_hostname, parse_retry_after

_logger = logging.getLogger(__name__)


def retrieve_resource_length_in_bytes(
    url: str,
    rate_limiter: KeyedRateLimiter,
    session: requests.Session | None = None,
    max_attempts: int = 3,
) -> int:
    """Retrieve the length of a resource in bytes from its URL.

    :param url: The URL of the resource.
    :param rate_limiter: An instance of KeyedRateLimiter to handle rate-limiting based on the hostname.
    :param session: Optional requests.Session to use for the request. If None, a new session will be
        created.

    :return: The length of the resource in bytes.
    :raises ValueError: If the resource length cannot be retrieved or if the response status code is not 200.
    :raises RateLimitedError: If the request is rate-limited and exceeds the maximum number of attempts.
    """
    _logger.debug("Retrieving resource length for URL: %s", url)
    key = get_hostname(url)
    for attempt in range(max_attempts):
        rate_limiter.acquire(key)
        if session is None:
            rsp = requests.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
        else:
            rsp = session.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)

        if rsp.status_code == 200:
            length = int(rsp.headers.get("Content-Length", 0))
            _logger.debug("Resource length for URL %s: %s bytes", url, length)
            return length
        elif rsp.status_code == 429:
            retry_after = parse_retry_after(rsp.headers.get("Retry-After"))
            rate_limiter.note_rate_limited(key, retry_after or 0.0)
        else:
            rsp.raise_for_status()

    raise RateLimitedError(
        f"Exceeded {max_attempts} attempts to retrieve resource length for URL: {url}"
    )


def retrieve_resource(
    url: str,
    destination: Path,
    rate_limiter: KeyedRateLimiter,
    session: requests.Session | None = None,
    max_attempts: int = 3,
    chunk_size: int = 8192,
    enable_tqdm: bool = False,
) -> None:
    """Download a resources to a file given its URL.

    :param url: The URL of the resourcee.
    :param destination: The path to save the downloaded resource.
    :param rate_limiter: An instance of KeyedRateLimiter to handle rate-limiting based on the hostname.
    :param session: Optional requests.Session to use for downloading. If None, a new session will be
        created.
    :param max_attempts: Maximum number of attempts to download the resource in case of rate-limiting.
    :param chunk_size: The size of the chunks to read from the response stream.
    :param enable_tqdm: Whether to enable the tqdm progress bar for the download.

    :raises RateLimitedError: If the download is rate-limited and exceeds the maximum number of attempts.
    """
    _logger.debug("Downloading resource from URL: %s to destination: %s", url, destination)
    key = get_hostname(url)
    rate_limiter.acquire(key)
    for attempt in range(max_attempts):
        if session is None:
            rsp = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        else:
            rsp = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)

        if rsp.status_code == 429:
            retry_after = parse_retry_after(rsp.headers.get("Retry-After"))
            rate_limiter.note_rate_limited(key, retry_after or 0.0)
        else:
            rsp.raise_for_status()
            file_size_bytes = int(rsp.headers.get("Content-Length", 0))
            with destination.open("wb") as f:
                if enable_tqdm:
                    for chunk in tqdm(
                        rsp.iter_content(chunk_size=chunk_size), total=file_size_bytes / chunk_size
                    ):
                        f.write(chunk)
                else:
                    for chunk in rsp.iter_content(chunk_size=chunk_size):
                        f.write(chunk)
            return
