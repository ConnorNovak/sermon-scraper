import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Sequence
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)


def get_hostname(url: str) -> str:
    """Extract the hostname from a URL.

    :param url: The URL to extract the hostname from.
    :return: The hostname, or the full url if it cannot be extracted.
    """
    try:
        parsed_url = urlparse(url)
        if parsed_url.hostname is None:
            raise ValueError(f"URL '{url}' does not contain a valid hostname.")
        return parsed_url.hostname
    except Exception as e:
        _logger.error("Error parsing URL '%s': %s", url, e)
        return url  # Fallback to returning the full URL if parsing fails


def log_level_type(value: str) -> int:
    """Convert a string log level to the corresponding logging module constant."""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return int(getattr(logging, value.upper()))
    except AttributeError:
        raise ValueError(f"Invalid log level: {value}")


def slugify(text: str) -> str:
    """Convert a string into a slug suitable for filenames or URLs."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def sort_by_host(urls: Sequence[str]) -> dict[str, list[str]]:
    """Sort a list of URLs by their hostnames.

    :param urls: A sequence of URLs to sort.
    :return: A list of URLs sorted by their hostnames.
    """
    sorted_urls: dict[str, list[str]] = {}
    for url in urls:
        host = get_hostname(url)
        if host not in sorted_urls:
            sorted_urls[host] = []
        sorted_urls[host].append(url)
    return sorted_urls


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After is either delta-seconds or an HTTP-date (RFC 7231)."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((dt - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except TypeError, ValueError:
        return None
