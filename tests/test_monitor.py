from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

SPEC = importlib.util.spec_from_file_location("monitor", Path(__file__).resolve().parents[1] / "monitor.py")
monitor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)
CANARY = "never-log-this-fixture-value"
TARGET = monitor.TARGETS[0]


class Response(io.BytesIO):
    def __init__(self, body=None, status=200):
        super().__init__(TARGET.body_contains.encode() if body is None else body)
        self.status = status

    def getcode(self):
        return self.status


class MonitorTests(unittest.TestCase):
    def probe(self, response=None, error=None):
        with patch.object(monitor.urllib.request.OpenerDirector, "open", return_value=response,
                          side_effect=error) as opened:
            result = monitor.probe(TARGET)
        return result, opened

    def test_success_has_fixed_get_without_credentials_and_proxy(self):
        original = monitor.urllib.request.build_opener
        with patch.object(monitor.urllib.request, "build_opener", wraps=original) as built:
            with patch.dict(os.environ, {"HTTPS_PROXY": "https://" + CANARY}):
                result, opened = self.probe(Response())
        self.assertEqual(result, (True, 200, "MATCH"))
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, TARGET.url)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.get_header("Cookie"))
        self.assertEqual(request.get_header("User-agent"), "public-web-monitor/1")
        self.assertEqual(opened.call_args.kwargs["timeout"], 10)
        self.assertEqual(built.call_args.args[0].proxies, {})

    def test_redirect_is_rejected_and_never_followed(self):
        error = urllib.error.HTTPError(TARGET.url, 302, CANARY, {}, io.BytesIO(CANARY.encode()))
        result, opened = self.probe(error=error)
        self.assertEqual(result, (False, 302, "REDIRECT_REJECTED"))
        self.assertEqual(opened.call_count, 1)
        self.assertIsNone(monitor.NoRedirect().redirect_request(None, None, 302, CANARY, {}, "https://other.test"))

    def test_body_limit_exact_boundary_and_content_status_mismatches(self):
        prefix = TARGET.body_contains.encode()
        cases = [(prefix + b"x" * (monitor.MAX_BODY - len(prefix)), 200, "MATCH"),
                 (prefix + b"x" * (monitor.MAX_BODY + 1 - len(prefix)), 200, "BODY_TOO_LARGE"),
                 (CANARY.encode(), 200, "CONTENT_MISMATCH"),
                 (CANARY.encode(), 503, "STATUS_MISMATCH")]
        for body, status, category in cases:
            with self.subTest(category=category):
                result, _ = self.probe(Response(body, status))
                self.assertEqual(result[2], category)
                self.assertEqual(result[0], category == "MATCH")

    def test_timeout_network_error_and_unexpected_error_are_redacted(self):
        for error, category in [(TimeoutError(CANARY), "TIMEOUT"),
                                (urllib.error.URLError(TimeoutError(CANARY)), "TIMEOUT"),
                                (urllib.error.URLError(CANARY), "NETWORK_ERROR"),
                                (ValueError(CANARY), "INVALID_RESPONSE")]:
            with self.subTest(category=category):
                result, _ = self.probe(error=error)
                self.assertEqual(result, (False, None, category))
        output = io.StringIO()
        with patch.object(monitor, "check_target", side_effect=RuntimeError(CANARY)), redirect_stdout(output):
            self.assertEqual(monitor.main([]), 1)
        self.assertEqual(output.getvalue(), "FAIL monitor INTERNAL_ERROR\n")

    def test_retry_once_only_after_failure_and_returns_final_outcome(self):
        success = (True, 200, "MATCH")
        failure = (False, 503, "STATUS_MISMATCH")
        for results, calls, sleep_calls, passed in [([success], 1, 0, True),
                                                   ([failure, success], 2, 1, True),
                                                   ([failure, failure], 2, 1, False)]:
            with self.subTest(calls=calls, passed=passed):
                output = io.StringIO()
                with patch.object(monitor, "probe", side_effect=results) as probe:
                    with patch.object(monitor.time, "sleep") as sleep, redirect_stdout(output):
                        result = monitor.check_target(TARGET)
                self.assertEqual(probe.call_count, calls)
                self.assertEqual(sleep.call_count, sleep_calls)
                if sleep_calls:
                    sleep.assert_called_once_with(5)
                self.assertEqual(result.passed, passed)
                self.assertEqual(result.attempts, calls)
                self.assertTrue(result.checked_at.endswith("Z"))

    def test_unknown_target_never_builds_http_client(self):
        target = monitor.Target(CANARY, "http://127.0.0.1/", 200, CANARY)
        with patch.object(monitor.urllib.request, "build_opener") as built:
            self.assertEqual(monitor.probe(target), (False, None, "TARGET_NOT_ALLOWED"))
        built.assert_not_called()

    def test_simulated_failure_is_no_network_and_writes_fixed_utc_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            output = io.StringIO()
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                with patch.object(monitor, "check_target", side_effect=AssertionError("no checks")):
                    with patch.object(monitor.urllib.request, "build_opener", side_effect=AssertionError("no network")):
                        with redirect_stdout(output):
                            self.assertEqual(monitor.main(["--simulate-failure"]), 1)
            self.assertIn("SIMULATED_FAILURE", output.getvalue())
            self.assertIn("SIMULATED_FAILURE", summary.read_text())
            self.assertRegex(summary.read_text(), r"UTC: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

    def test_all_targets_checked_summary_written_and_one_failure_fails_job(self):
        outcomes = [monitor.Result(target.id, index > 0, 200 if index else 503,
                                   "MATCH" if index else "STATUS_MISMATCH", 1 if index else 2,
                                   "2026-09-19T00:00:00Z")
                    for index, target in enumerate(monitor.TARGETS)]
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                with patch.object(monitor, "check_target", side_effect=outcomes) as checked:
                    self.assertEqual(monitor.main([]), 1)
            self.assertEqual(checked.call_count, len(monitor.TARGETS))
            content = summary.read_text()
            self.assertIn("| animeirank | FAIL | 503", content)
            self.assertIn("| star-hunt | PASS | 200", content)
            self.assertIn("| public-app-directory | PASS | 200", content)
            self.assertNotIn(CANARY, content)

    def test_invalid_cli_arguments_never_echo_input(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(monitor.main([CANARY]), 2)
        self.assertEqual(output.getvalue(), "FAIL monitor INVALID_ARGUMENT\n")


if __name__ == "__main__":
    unittest.main()
