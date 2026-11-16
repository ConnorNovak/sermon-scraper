from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "local_backup.csv"

#: Seconds to wait for a connection to be established before giving up.
CONNECT_TIMEOUT_SECONDS = 5

#: Seconds to wait for a response to start streaming back before giving up.
READ_TIMEOUT_SECONDS = 30

#: Ready to pass straight to requests' `timeout=` kwarg: (connect, read).
REQUEST_TIMEOUT = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
