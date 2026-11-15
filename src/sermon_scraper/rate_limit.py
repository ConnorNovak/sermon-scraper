"""Tooling for selective throttling of requests to specific hosts in an attempt to avoid
rate limiting via HTTP 429 and 406 responses.
"""

import logging
import threading
import time

import requests

_logger = logging.getLogger(__name__)


class RateLimitedError(Exception):
    """Exception raised when a request is rate-limited."""


class KeyedRateLimiter:
    """Thread-safe, gate to rate-limit calls per key. A calling thread with a key will block until
    the next allowed time for that key. Keys are typically hostnames, but could be any string.

    Intended usage:

    ``
        rate_limiter = KeyedRateLimiter()

        # In a thread that wants to make a request to a specific host:
        rate_limiter.acquire(hostname)
        try:
            # Make the request here
            ...
        except RateLimitException as e:
            retry_after_s = parse_retry_after(e.response.headers.get("Retry-After"))
            if retry_after_s is not None:
                rate_limiter.note_rate_limited(hostname, retry_after_s)
    ```
    """

    def __init__(self, max_wait_s: float | None = 60.0, throttle_mode: int = 0) -> None:
        """Initialize the KeyedRateLimiter.

        :param max_wait_s: Maximum wait time (s). If a rate limit requested exceeds this, it will
            be thresholded to this value. if None, no thresholding will be applied.
        :param throttle_mode: Throttling mode:
            0: No throttling beyond the rate-limited request.
            1: Self-throttling at the rate limit pace (i.e., if a request is rate-limited for 10
                seconds, the next request will be delayed by at least 10 seconds).
            default is 0.
        """
        #: lock to protect modifying internal state.
        self._lock = threading.Lock()

        #: Mapping of keys to the next allowed time (using time.monotonic()) for that key.
        self._next_allowed: dict[str, float] = {}

        #: Mapping of keys to the minimum interval between calls for that key.
        self._min_interval: dict[str, float] = {}

        self.max_wait_s = max_wait_s
        self.throttle_mode = throttle_mode

    def acquire(self, key: str) -> None:
        """Block until the next allowed time for the given key.

        :param key: The key to acquire the rate limit for.
        """
        while True:
            with self._lock:
                now = time.monotonic()
                next_allowed = self._next_allowed.get(key, 0.0)
                if now >= next_allowed:
                    # If no rate-limiting has been noted for this key
                    interval = self._min_interval.get(key, 0.0)
                    self._next_allowed[key] = now + interval
                    return
                wait_time = next_allowed - now

            # sleep OUTSIDE the lock — threads referencing other keys unblocked
            time.sleep(wait_time)

    def note_rate_limited(self, key: str, retry_after_s: float) -> None:
        """Note that a request for the given key was rate-limited and the next allowed time should
        be delayed by the given retry_after_s.

        :param key: The key that was rate-limited.
        :param retry_after_s: The number of seconds to wait before the next allowed request for
            this key.

        :raises NotImplementedError: If the throttle_mode is not recognized.
        """
        _logger.debug("Rate limit noted for key '%s', retry after %.2f seconds", key, retry_after_s)
        if self.max_wait_s is not None and retry_after_s >= self.max_wait_s:
            _logger.warning(
                "Rate limit for key '%s' exceeds max_wait_s (%.2f seconds), Thresholding.",
                key,
                retry_after_s,
            )
            retry_after_s = self.max_wait_s

        with self._lock:
            self._next_allowed[key] = time.monotonic() + retry_after_s
            match self.throttle_mode:
                case 0:  # no throttling beyond the rate-limited request
                    self._min_interval[key] = self._min_interval.get(key, 0.0)
                case 1:  # self-throttling at the rate limit pace
                    self._min_interval[key] = max(self._min_interval.get(key, 0.0), retry_after_s)
                case _:
                    raise NotImplementedError(f"Unknown throttle_mode: {self.throttle_mode}")


#: A retry strategy that only handles server errors (5xx), not rate-limiting (429) which is handled
# separately by a KeyedRateLimiter.
RetryAdjustedforRateLimiter = requests.adapters.Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],  # 429 handled by KeyedRateLimiter
    respect_retry_after_header=False,
)
