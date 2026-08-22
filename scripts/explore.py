"""
Drop into a Python REPL with an authenticated `requests.Session` against
the Subsplash API, for poking around by hand.

Usage:
    python explore.py

Then in the REPL:
    >>> r = get(f"{API_BASE}/media/v1/media-series", params={"filter[app_key]": APP_KEY, "page[size]": 5})
    >>> r["_embedded"]["media-series"][0]
"""

import code

import plac  # type: ignore [import-untyped]
import requests

from sermon_scraper.subsplash import API_BASE, APP_KEY, get_guest_token


def get(session: requests.Session, url: str, params) -> dict:
    """GET url with the authed session and return parsed JSON."""
    rsp = session.get(url, params=params)
    rsp.raise_for_status()
    return rsp.json()


def main() -> None:
    print("fetching guest token...")
    token = get_guest_token()

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    print(f"ready. session authed, APP_KEY={APP_KEY!r}, API_BASE={API_BASE!r}")
    print(
        "try: get(f'{API_BASE}/media/v1/media-series', params={'filter[app_key]': APP_KEY, 'page[size]': 5})"
    )
    code.interact(local=dict(globals(), **locals()))


if __name__ == "__main__":
    plac.call(main)
