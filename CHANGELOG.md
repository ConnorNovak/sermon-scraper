# Changelog

All notable changes to this project will be documented here.
Format: [Semantic Versioning](https://semver.org)

## [Unreleased]
### Added
- `scripts/download_files.py`, which downloads every link in the `audio` column of an Ekklesia
    CSV into a target directory. It copies the cleaned CSV there, skips files already present
    unless told not to cache, and appends one JSON line per file to `download.log`. The
    `subsplash` source is not implemented yet. The Ekklesia cleaning it applies is
    `sermon_scraper.ekklesia.clean_df_ekklesia`.
- `sermon_scraper.rate_limit`: `KeyedRateLimiter`, which spaces requests per host and backs off
    when a host answers 429, and `RateLimitedError`. One limiter must be shared by every worker
    hitting a host; a fresh one per request limits nothing.
- `sermon_scraper.retrieve`: `retrieve_resource_length_in_bytes` (HEAD) and `retrieve_resource`
    (streamed GET, with an optional tqdm progress bar). Both honour `Retry-After` and raise
    `RateLimitedError` once `max_attempts` is spent.
- `REQUEST_TIMEOUT` (5 s to connect, 30 s to read) in `sermon_scraper.constants`, passed to
    every `requests` call in `retrieve`.
- `get_hostname`, `sort_by_host`, `log_level_type` and `parse_retry_after` in
    `sermon_scraper.utilities`. `parse_retry_after` reads both the delta-seconds and HTTP-date
    forms of `Retry-After`.
- `tests/`, with `tests/gen_ai/` for tests written entirely by an AI tool. Those are disposable,
    unlike the tests beside them, which capture a designed behavior.

### Changed
- `retrieve_resource` and `retrieve_resource_length_in_bytes` moved from
    `sermon_scraper.utilities` to `sermon_scraper.retrieve`, and now take a `rate_limiter`.
    **Breaking** for anything importing them from the old place.

### Removed
- `scripts/temp.py` and the checked-in `data/sermonExportAug_03_2026.csv` export.

---

## [v0.2.0]
### Added
- `notebooks/` folder for `.ipynb` files used to explore the captured data.
- A new notebook: `subsplash-ekklesia-compare.ipynb`, for comparing the Subsplash and Ekklesia data
    side by side, with `jupyterlab` as a dev dependency and `dtale` and `matplotlib` as dependencies
    to run it.

---

## [v0.1.0]
### Added
- A crawler for a Subsplash-hosted church site (`sermon_scraper.subsplash`). It signs in as a
    guest with Playwright, reads the site's JSON API, and walks every series and episode.
- Downloading of each episode's audio, video and cover image, tagging the MP3 with its
    metadata through `mutagen`. Files already on disk are skipped.
- `scripts/explore.py` and `scripts/scrape_speakers.sh`.
- `data/sermonExportAug_03_2026.csv`, a snapshot of the Ekklesia export, and a README.

---
