"""Owner-assigned incident notifications in this repository, using GITHUB_TOKEN."""

import http.client
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "Kanshikun/public-web-monitor"
OWNER = "Kanshikun"
BOT = "github-actions[bot]"
API_ROOT = "https://api.github.com"
REPO_PATH = "/repos/" + REPOSITORY
TITLE = "[monitor] Public web availability"
MARKER = "<!-- public-web-monitor:availability:v1 -->"
OUTAGE_TEXT = ("公開ページ監視が失敗しました。"
               "[最新のActions実行](https://github.com/Kanshikun/public-web-monitor/actions)を確認してください。\n"
               "担当はリポジトリ所有者です。秘密値や応答本文は記録しません。")
RECOVERED_TEXT = "RECOVERED: 設定した公開ページの確認がすべて成功しました。"
MAX_API_BODY = 512 * 1024
MAX_PAGES = 5


class NotificationError(Exception):
    """No raw remote response or exception is allowed in diagnostics."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require(condition):
    if not condition:
        raise NotificationError()


def outage_body(cycle):
    require(isinstance(cycle, str) and re.fullmatch(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,9}", cycle) is not None)
    return f"{MARKER}\n<!-- incident-run:{cycle} -->\n\n{OUTAGE_TEXT}"


def recovery_body(cycle):
    outage_body(cycle)  # Validate the same stable incident ID.
    return f"{RECOVERED_TEXT}\n\n<!-- public-web-monitor:recovered:{cycle} -->"


def api_request(token, method, path, *, payload=None, query=None):
    require(method in ("GET", "POST", "PATCH"))
    require(re.fullmatch(re.escape(REPO_PATH) + r"/issues(?:/[1-9][0-9]*(?:/comments)?)?", path) is not None)
    url = API_ROOT + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "public-web-monitor/1"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=10) as response:
            require(response.getcode() == (201 if method == "POST" else 200))
            body = response.read(MAX_API_BODY + 1)
            require(len(body) <= MAX_API_BODY)
            return json.loads(body)
    except (OSError, ValueError, UnicodeError, urllib.error.URLError, socket.timeout,
            http.client.HTTPException):
        raise NotificationError() from None


def bot_author(value):
    return isinstance(value, dict) and value.get("login") == BOT and value.get("type") == "Bot"


def owned_issue(value):
    """Unrelated issues are ignored; a damaged dedicated issue blocks mutation."""
    require(isinstance(value, dict))
    body = value.get("body")
    if not bot_author(value.get("user")):
        return None
    marked = isinstance(body, str) and MARKER in body
    if value.get("title") != TITLE and not marked:
        return None
    require(value.get("title") == TITLE and marked)
    require("pull_request" not in value and value.get("repository_url") == API_ROOT + REPO_PATH)
    number = value.get("number")
    require(type(number) is int and number > 0)
    require(value.get("state") in ("open", "closed"))
    assignees = value.get("assignees")
    require(isinstance(assignees, list) and len(assignees) == 1
            and isinstance(assignees[0], dict) and assignees[0].get("login") == OWNER)
    match = re.fullmatch(re.escape(MARKER) + r"\n<!-- incident-run:([1-9][0-9]{0,19}-[1-9][0-9]{0,9}) -->\n\n"
                         + re.escape(OUTAGE_TEXT), body)
    require(match is not None)
    return {"number": number, "state": value["state"], "cycle": match[1]}


def pages(token, path, query=None):
    for page in range(1, MAX_PAGES + 1):
        result = api_request(token, "GET", path, query={**(query or {}), "per_page": 100, "page": page})
        require(isinstance(result, list) and len(result) <= 100)
        yield from result
        if len(result) < 100:
            return
    # No mutation if the complete result set could not be inspected.
    raise NotificationError()


def find_issue(token):
    matches = []
    for value in pages(token, REPO_PATH + "/issues", {"state": "all", "creator": BOT, "sort": "created", "direction": "asc"}):
        record = owned_issue(value)
        if record is not None:
            matches.append(record)
    require(len(matches) <= 1)
    if not matches:
        return None
    # Recheck ownership and current state immediately before any change.
    record = owned_issue(api_request(token, "GET", REPO_PATH + f"/issues/{matches[0]['number']}"))
    require(record is not None and record["number"] == matches[0]["number"])
    return record


def recovery_exists(token, issue):
    expected = recovery_body(issue["cycle"])
    found = False
    for comment in pages(token, REPO_PATH + f"/issues/{issue['number']}/comments"):
        require(isinstance(comment, dict))
        if bot_author(comment.get("user")) and comment.get("body") == expected:
            found = True
    return found


def require_unchanged(token, issue):
    current = owned_issue(api_request(token, "GET", REPO_PATH + f"/issues/{issue['number']}"))
    require(current == issue)


def sync_incident(healthy):
    require(type(healthy) is bool)
    token = os.environ.get("GH_TOKEN", "")
    cycle = os.environ.get("GITHUB_RUN_ID", "") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "")
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and 0 < len(token) <= 8192 and not any(c.isspace() or ord(c) < 32 for c in token))
    outage_body(cycle)
    issue = find_issue(token)
    if issue is None:
        if healthy:
            return "NO_OPEN_INCIDENT"
        created = owned_issue(api_request(token, "POST", REPO_PATH + "/issues",
                                         payload={"title": TITLE, "body": outage_body(cycle), "assignees": [OWNER]}))
        require(created is not None and created["state"] == "open" and created["cycle"] == cycle)
        return "ISSUE_CREATED"
    path = REPO_PATH + f"/issues/{issue['number']}"
    if not healthy:
        if issue["state"] == "open":
            return "OUTAGE_ALREADY_OPEN"
        reopened = owned_issue(api_request(token, "PATCH", path,
                                          payload={"state": "open", "body": outage_body(cycle), "assignees": [OWNER]}))
        require(reopened is not None and reopened["state"] == "open" and reopened["cycle"] == cycle)
        return "ISSUE_REOPENED"
    if issue["state"] == "closed":
        return "NO_OPEN_INCIDENT"
    if not recovery_exists(token, issue):
        require_unchanged(token, issue)
        expected = recovery_body(issue["cycle"])
        comment = api_request(token, "POST", path + "/comments", payload={"body": expected})
        require(isinstance(comment, dict) and bot_author(comment.get("user")) and comment.get("body") == expected)
    require_unchanged(token, issue)
    closed = owned_issue(api_request(token, "PATCH", path, payload={"state": "closed", "state_reason": "completed"}))
    require(closed is not None and closed["state"] == "closed" and closed["cycle"] == issue["cycle"])
    return "ISSUE_RECOVERED"
