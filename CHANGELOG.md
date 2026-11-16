# Changelog

All notable changes to this project will be documented here.
Format: [Semantic Versioning](https://semver.org)

## [v0.2.0]
### Added
- `notebooks/subsplash-ekklesia-compare.ipynb`, for comparing the Subsplash and Ekklesia data
    side by side, with `jupyterlab` as a dev dependency and `dtale` and `matplotlib` as
    dependencies to run it.

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
