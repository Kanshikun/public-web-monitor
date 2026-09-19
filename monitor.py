#!/usr/bin/env python3
"""Unauthenticated checks for two fixed public landing pages; stdlib only."""

from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import os
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 10
MAX_BODY = 256 * 1024
RETRY_SECONDS = 5


@dataclass(frozen=True)
class Target:
    id: str
    url: str
    expected_status: int
    body_contains: str


TARGETS = (
    Target("animeirank", "https://animeirank.com/auth/login", 200, "アニメイランク"),
    Target("star-hunt", "https://star-hunt-v2.gattsu01.chatgpt.site/", 200, "Star Hunt"),
)


@dataclass(frozen=True)
class Result:
    id: str
    passed: bool
    status: int | None
    category: str
    attempts: int
    checked_at: str


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(target):
    # No CLI/config URL is accepted. Every request must match this exact allowlist.
    if target not in TARGETS:
        return False, None, "TARGET_NOT_ALLOWED"
    status = None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(
            target.url, method="GET",
            headers={"User-Agent": "public-web-monitor/1", "Accept": "text/html"})
        try:
            response = opener.open(request, timeout=TIMEOUT_SECONDS)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.getcode()
            if 300 <= status < 400:
                return False, status, "REDIRECT_REJECTED"
            if status != target.expected_status:
                return False, status, "STATUS_MISMATCH"
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                return False, status, "BODY_TOO_LARGE"
            if target.body_contains not in body.decode("utf-8", errors="replace"):
                return False, status, "CONTENT_MISMATCH"
            return True, status, "MATCH"
    except (TimeoutError, socket.timeout):
        return False, status, "TIMEOUT"
    except urllib.error.URLError as error:
        category = "TIMEOUT" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "NETWORK_ERROR"
        return False, status, category
    except (OSError, ValueError, http.client.HTTPException):
        return False, status, "INVALID_RESPONSE"


def check_target(target):
    if target not in TARGETS:
        raise ValueError()  # Never log an unvalidated ID or URL.
    for attempt in (1, 2):
        passed, status, category = probe(target)
        result = Result(target.id, passed, status, category, attempt, utc_now())
        print(f"{'PASS' if passed else 'FAIL'} {result.id} attempt={attempt} "
              f"status={status if status is not None else 'none'} {category} utc={result.checked_at}", flush=True)
        if passed or attempt == 2:
            return result
        time.sleep(RETRY_SECONDS)


def write_summary(results, *, simulated=False):
    location = os.environ.get("GITHUB_STEP_SUMMARY")
    if not location:
        return
    lines = ["## Public web monitor", "", f"UTC: {utc_now()}", ""]
    if simulated:
        lines.append("**FAIL — SIMULATED_FAILURE** (manual notification test; no network requests)")
    else:
        lines.extend(["| Target | Result | HTTP | Category | Attempts | Checked at (UTC) |",
                      "| --- | --- | --- | --- | --- | --- |"])
        for result in results:
            lines.append(f"| {result.id} | {'PASS' if result.passed else 'FAIL'} | "
                         f"{result.status if result.status is not None else 'none'} | "
                         f"{result.category} | {result.attempts} | {result.checked_at} |")
        lines.extend(["", "Checks cover public landing pages only; application functions were not tested."])
    with Path(location).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--simulate-failure"]):
        print("FAIL monitor INVALID_ARGUMENT")
        return 2
    try:
        if args == ["--simulate-failure"]:
            print(f"FAIL monitor SIMULATED_FAILURE utc={utc_now()}")
            write_summary([], simulated=True)
            return 1
        results = [check_target(target) for target in TARGETS]
        write_summary(results)
        return 0 if all(result.passed for result in results) else 1
    except KeyboardInterrupt:
        print("FAIL monitor INTERRUPTED")
        return 130
    except Exception:
        # Never print exception text, response bodies/headers, or environment values.
        print("FAIL monitor INTERNAL_ERROR")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
