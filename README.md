# Overview

I want to download all of the .mp3 files from CCTheRock's subsplash website and relate them
to their metadata, which I also want to download.

https://subsplash.com/calvarychapeltherock/sermons

# Notebook

I use Jupyter notebooks to explore data.

To run the jupyter server in the current environment, run:
```
uv run jupyter lab
```

Then open the notebook in your browser at http://localhost:8888/lab

# Notes
- Site is fully server-site rendering, meaning that the server sends full HTML pages, no nedd for 
JS rendering
- Unable to find a sitemap.xml (robots.txt points to a sitemap.xml, but it doesn't exist)
- Some category pages (New Testament, Old Testament, Special Series -> per-book lists) are
  client-rendered and don't have episode links in the raw HTML, unlike the top index and the
  "Current Studies" category

## Update: found the underlying JSON API

The site's frontend calls a public JSON:API/HAL API directly. Easier and more robust than
scraping HTML, so `main.py` uses this instead of BeautifulSoup:

- `GET core.subsplash.com/media/v1/media-series?filter[app_key]=6QVR5X` — every series
  (books, "Current Studies", speaker collections, etc.), paginated via `_links.next.href`.
  `app_key` for this org is `6QVR5X`.
- `GET core.subsplash.com/media/v1/media-items?filter[media_series]=<id>&include=images,audio.audio-outputs`
  — episodes for one series: title, subtitle (scripture ref), date, speaker, slug, plus embedded
  audio (`_embedded.audio._embedded['audio-outputs'][0]._links.related.href` = direct mp3 CDN
  link) and images.
- Requires `Authorization: Bearer <guest_token>` header. The token is a public/guest JWT the
  frontend mints for itself (not user-specific) — visible in browser localStorage as
  `guest_token`. Lives ~2.5 hours. `main.py` grabs one at startup via a headless Playwright
  page load rather than reverse-engineering the mint endpoint (`core.subsplash.com/tokens/v1/token`,
  needs a `client_secret` buried in a minified JS bundle — not worth it for a one-off script).
- `explore.py` drops into a Python REPL with an authed session for poking at the API by hand.

## Update: Now Ekklesia
I've got the login for the backend of Ekklesia now. It seems easier? An easily downloadable .csv
of the database is available, so I'll just grab that and go from there? Maybe I can scrape an
identical csv from subsplash...

# Usage

To run the `explore.py` script and poke around at the data downloaded from Ekklesia and Subsplash, run:
```
uv run jupyter lab notebooks/###.ipynb
```

# How-to Instructions

The following are some quick-start howtos to perform certain tasks.

## Download all of the .mp3 files and metadata from Ekklesia

1. Download the Ekklesia .csv (see instructions in ./data/ekklesia/README.md)

2. Run the download_files script.
```
uv run scripts/download_files.py ./data/ekklesia/sermonExportSeb_22_2026.csv ./data/ekklesia/sermons/
```
