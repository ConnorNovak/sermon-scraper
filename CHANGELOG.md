# Changelog

All notable changes to this project will be documented here.
Format: [Semantic Versioning](https://semver.org)

## [Unreleased]
### Added
- `scripts/download_files.py`, which downloads every link in the `audio` column of an Ekklesia
    CSV into a target directory. It copies the cleaned CSV there, skips files already present
    unless told not to cache, and appends one JSON line per file to `download.log`. The
    `subsplash` source is not implemented yet.
- `sermon_scraper.rate_limit`: `KeyedRateLimiter`, which spaces requests per host and backs off
    when a host answers 429, and `RateLimitedError`. One limiter must be shared by every worker
    hitting a host; a fresh one per request limits nothing.
- `sermon_scraper.retrieve`: `retrieve_resource_length_in_bytes` (HEAD) and `retrieve_resource`
    (streamed GET, with an optional tqdm progress bar). Both honour `Retry-After` and raise
    `RateLimitedError` once `max_attempts` is spent.
- `REQUEST_TIMEOUT` (5 s to connect, 30 s to read) in `sermon_scraper.constants`, passed to
    every `requests` call.
- `SermonResource`, one pydantic model for a sermon row from either Ekklesia or Subsplash,
    including optional `audio_size_mb`, `video_size_mb` and `notes_size_mb`.
- `subsplash.export_csv` crawls every series and episode and writes them as `SermonResource`
    rows, in the same columns as the Ekklesia export.
- `get_hostname`, `sort_by_host` and `parse_retry_after` in `sermon_scraper.utilities`.
    `parse_retry_after` reads both the delta-seconds and HTTP-date forms of `Retry-After`.
- TUI commands `calculate` (resource sizes, and an audio `source` column of S3, Rackspace
    `rackcdn` or Unknown), `report` (a rich console report of overview, speakers and series
    that exports to HTML) and `download`.
- `runner.py`, with `format` (`ruff`), `lint` (`mypy`), `test` (`unittest`) and `all` commands.

### Changed
- `calculate` caches: a size column that already exists is only filled in for rows missing a
    value. `overwrite` re-fetches every row.
- `retrieve_resource_length_in_bytes` moved from `sermon_scraper.utilities` to
    `sermon_scraper.retrieve`, and now takes a `rate_limiter`. **Breaking** for anything
    importing it from the old place.
- `TUI.calculate` no longer takes `no_update`, which was never read.

### Removed
- `scripts/temp.py` and the checked-in `data/sermonExportAug_03_2026.csv` export.

### Fixed
- `calculate` wrote each size to the wrong row. Results were collected in completion order and
    assigned back by position, so any row that finished out of order took another row's size.
    Each result is now written to the row it came from, and `max_worker_count` is honoured
    rather than a fixed 10.
- `retrieve_resource` downloaded every file up to `max_attempts` times. Nothing left the retry
    loop after a successful download, so each file was fetched three times by default.
- `TUI.download_resources` never reported a failure and never wrote a file: `executor.map`'s
    results were not read, hiding a `TypeError` from adding a `str` to a `Path`. It now reads
    every result.
- The TUI's `quit` command hung. `plac` catches `SystemExit` raised by a command, so the
    interpreter loop carried on; it now raises `plac.Interpreter.Exit`.
- Requests no longer hang forever: `subsplash.api_get`, `download_file` and `fetch_cover`
    had no timeout.

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
