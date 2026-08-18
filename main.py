import plac  # type: ignore [import-untyped]

from sermon_scraper.ui.tui import main

plac.call(main)
# plac.call(download_series)
