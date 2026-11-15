# Changelog

All notable changes to this project will be documented here.
Format: [Semantic Versioning](https://semver.org)

## [v0.2.0]
### Added
- A TUI for working on an Ekklesia sermon CSV, started by `main.py`
    (`sermon_scraper.ui.tui`). Its commands are `load`, `show`, `save`, `calculate`, `download`,
    `report` and `quit`.
- `calculate` fills in an audio, video or notes size column, or an audio `source` column that
    classifies each link as S3, Rackspace `rackcdn` or Unknown.
- `report`, a rich console report of the overview, the speakers and the series, each with its
    sizes and audio sources, that exports to HTML.
- `runner.py`, with `format` (`ruff`), `lint` (`mypy`), `test` (`unittest`) and `all` commands.
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
