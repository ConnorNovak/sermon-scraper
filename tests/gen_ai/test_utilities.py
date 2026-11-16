"""AI-generated unit tests for `sermon_scraper.utilities`."""

import logging
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from sermon_scraper.utilities import (
    get_hostname,
    log_level_type,
    parse_retry_after,
    slugify,
    sort_by_host,
)


class TestGetHostname(unittest.TestCase):
    def test_returns_host_of_a_plain_url(self) -> None:
        self.assertEqual(get_hostname("https://example.com/a/b.mp3"), "example.com")

    def test_drops_port_credentials_query_and_fragment(self) -> None:
        url = "https://user:pw@example.com:8443/path?q=1#frag"
        self.assertEqual(get_hostname(url), "example.com")

    def test_host_is_lowercased(self) -> None:
        self.assertEqual(get_hostname("HTTP://Example.COM/x"), "example.com")

    def test_subdomains_are_kept(self) -> None:
        self.assertEqual(get_hostname("https://ssl.cf2.rackcdn.com/x"), "ssl.cf2.rackcdn.com")

    def test_url_without_a_host_is_returned_whole_and_logged(self) -> None:
        url = "not-a-url/path"
        with self.assertLogs("sermon_scraper.utilities", level=logging.ERROR) as logs:
            self.assertEqual(get_hostname(url), url)
        self.assertEqual(len(logs.records), 1)

    def test_unparseable_url_is_returned_whole(self) -> None:
        url = "http://[invalid"
        with self.assertLogs("sermon_scraper.utilities", level=logging.ERROR):
            self.assertEqual(get_hostname(url), url)


class TestLogLevelType(unittest.TestCase):
    def test_integer_strings_are_taken_literally(self) -> None:
        self.assertEqual(log_level_type("10"), 10)
        self.assertEqual(log_level_type("0"), 0)

    def test_level_names_map_to_logging_constants(self) -> None:
        for name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            with self.subTest(name=name):
                self.assertEqual(log_level_type(name), getattr(logging, name))

    def test_level_names_are_case_insensitive(self) -> None:
        self.assertEqual(log_level_type("debug"), logging.DEBUG)
        self.assertEqual(log_level_type("Info"), logging.INFO)

    def test_unknown_name_raises_value_error_naming_the_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "nonsense"):
            log_level_type("nonsense")

    def test_empty_string_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            log_level_type("")


class TestSlugify(unittest.TestCase):
    def test_lowercases_and_joins_words_with_hyphens(self) -> None:
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_removes_punctuation(self) -> None:
        self.assertEqual(slugify("Hello, World!"), "hello-world")
        self.assertEqual(slugify("1 Samuel 14:1-23"), "1-samuel-141-23")

    def test_collapses_runs_of_separators(self) -> None:
        self.assertEqual(slugify("a   b__c--d _-_ e"), "a-b-c-d-e")

    def test_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(slugify("  padded title \n"), "padded-title")

    def test_keeps_non_ascii_word_characters(self) -> None:
        self.assertEqual(slugify("Café Séance"), "café-séance")

    def test_empty_and_punctuation_only_inputs_give_empty_slug(self) -> None:
        self.assertEqual(slugify(""), "")
        self.assertEqual(slugify("!?.,"), "")

    def test_result_has_no_whitespace_or_underscores(self) -> None:
        slug = slugify("Some_Title  with\tmixed\nwhitespace_and-hyphens")
        self.assertNotRegex(slug, r"[\s_]")

    def test_is_idempotent(self) -> None:
        for text in ("Hello, World!", "A  B_C-D", "Ruth: Part 1 (Redemption)"):
            with self.subTest(text=text):
                self.assertEqual(slugify(slugify(text)), slugify(text))


class TestSortByHost(unittest.TestCase):
    def test_empty_input_gives_empty_mapping(self) -> None:
        self.assertEqual(sort_by_host([]), {})

    def test_groups_urls_by_host(self) -> None:
        urls = [
            "https://a.example.com/1.mp3",
            "https://b.example.com/2.mp3",
            "https://a.example.com/3.mp3",
        ]
        self.assertEqual(
            sort_by_host(urls),
            {
                "a.example.com": ["https://a.example.com/1.mp3", "https://a.example.com/3.mp3"],
                "b.example.com": ["https://b.example.com/2.mp3"],
            },
        )

    def test_keeps_input_order_within_each_host(self) -> None:
        urls = [f"https://a.example.com/{i}.mp3" for i in (3, 1, 2)]
        self.assertEqual(sort_by_host(urls)["a.example.com"], urls)

    def test_every_url_appears_exactly_once(self) -> None:
        urls = ["https://a.com/1", "https://b.com/2", "https://a.com/1", "https://c.com/3"]
        grouped = sort_by_host(urls)
        flattened = [url for group in grouped.values() for url in group]
        self.assertCountEqual(flattened, urls)

    def test_hosts_differing_only_in_case_share_a_group(self) -> None:
        grouped = sort_by_host(["https://A.com/1", "https://a.com/2"])
        self.assertEqual(list(grouped), ["a.com"])

    def test_accepts_any_sequence(self) -> None:
        self.assertEqual(sort_by_host(("https://a.com/1",)), {"a.com": ["https://a.com/1"]})


class TestParseRetryAfter(unittest.TestCase):
    def test_none_gives_none(self) -> None:
        self.assertIsNone(parse_retry_after(None))

    def test_delta_seconds(self) -> None:
        self.assertEqual(parse_retry_after("120"), 120.0)
        self.assertEqual(parse_retry_after("0"), 0.0)

    def test_delta_seconds_ignore_surrounding_whitespace(self) -> None:
        self.assertEqual(parse_retry_after("  7 "), 7.0)

    def test_future_http_date_gives_remaining_seconds(self) -> None:
        when = datetime.now(timezone.utc) + timedelta(seconds=90)
        result = parse_retry_after(format_datetime(when, usegmt=True))
        assert result is not None
        self.assertGreater(result, 80.0)
        self.assertLessEqual(result, 90.0)

    def test_past_http_date_is_clamped_to_zero(self) -> None:
        self.assertEqual(parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT"), 0.0)

    def test_result_is_never_negative(self) -> None:
        for value in ("Wed, 21 Oct 2015 07:28:00 GMT", "0", "5"):
            with self.subTest(value=value):
                result = parse_retry_after(value)
                assert result is not None
                self.assertGreaterEqual(result, 0.0)

    def test_http_date_without_timezone_is_read_as_utc(self) -> None:
        when = datetime.now(timezone.utc) + timedelta(seconds=60)
        result = parse_retry_after(format_datetime(when.replace(tzinfo=None)))
        assert result is not None
        self.assertGreater(result, 50.0)
        self.assertLessEqual(result, 60.0)

    def test_garbage_gives_none(self) -> None:
        for value in ("", "soon", "12.5", "-3", "not a date"):
            with self.subTest(value=value):
                self.assertIsNone(parse_retry_after(value))


if __name__ == "__main__":
    unittest.main()
