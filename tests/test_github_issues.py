from contextlib import redirect_stdout
import io
import os
import unittest
from unittest.mock import patch
import urllib.error

import github_issues as notices
import monitor

CANARY = "fake-token-do-not-print"
CONTEXT = {"GH_TOKEN": CANARY, "GITHUB_ACTIONS": "true",
           "GITHUB_REPOSITORY": notices.REPOSITORY, "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1"}


def issue(state="open", cycle="55-1", number=1):
    return {"number": number, "title": notices.TITLE, "body": notices.outage_body(cycle),
            "state": state, "repository_url": notices.API_ROOT + notices.REPO_PATH,
            "user": {"login": notices.BOT, "type": "Bot"}, "assignees": [{"login": notices.OWNER}]}


def comment(cycle="55-1"):
    return {"user": {"login": notices.BOT, "type": "Bot"}, "body": notices.recovery_body(cycle)}


class Response(io.BytesIO):
    def __init__(self, body=b"[]", status=200):
        super().__init__(body)
        self.status = status

    def getcode(self):
        return self.status


class GitHubIssueTests(unittest.TestCase):
    def setUp(self):
        self.context = patch.dict(os.environ, CONTEXT, clear=True)
        self.context.start()
        self.addCleanup(self.context.stop)

    def sync(self, healthy, responses):
        with patch.object(notices, "api_request", side_effect=responses) as api:
            result = notices.sync_incident(healthy)
        return result, api

    def test_first_failure_creates_only_owner_assigned_dedicated_issue(self):
        result, api = self.sync(False, [[], issue(cycle="77-1")])
        self.assertEqual(result, "ISSUE_CREATED")
        self.assertEqual(api.call_args_list[0].kwargs["query"]["state"], "all")
        self.assertEqual(api.call_args_list[0].kwargs["query"]["creator"], notices.BOT)
        self.assertEqual(api.call_args.args[1:3], ("POST", notices.REPO_PATH + "/issues"))
        self.assertEqual(api.call_args.kwargs["payload"],
                         {"title": notices.TITLE, "body": notices.outage_body("77-1"), "assignees": ["Kanshikun"]})

    def test_open_failure_and_closed_success_do_not_add_comments(self):
        for healthy, state, expected in [(False, "open", "OUTAGE_ALREADY_OPEN"),
                                         (True, "closed", "NO_OPEN_INCIDENT")]:
            with self.subTest(state=state):
                result, api = self.sync(healthy, [[issue(state)], issue(state)])
                self.assertEqual(result, expected)
                self.assertTrue(all(call.args[1] == "GET" for call in api.call_args_list))
        result, api = self.sync(True, [[]])
        self.assertEqual(result, "NO_OPEN_INCIDENT")
        self.assertEqual(api.call_count, 1)

    def test_later_outage_reopens_same_issue_and_starts_new_cycle(self):
        result, api = self.sync(False, [[issue("closed")], issue("closed"), issue(cycle="77-1")])
        self.assertEqual(result, "ISSUE_REOPENED")
        self.assertEqual(api.call_args.args[1:3], ("PATCH", notices.REPO_PATH + "/issues/1"))
        self.assertEqual(api.call_args.kwargs["payload"]["body"], notices.outage_body("77-1"))
        self.assertFalse(any(call.args[1] == "POST" for call in api.call_args_list))

    def test_recovery_posts_fixed_comment_then_closes_same_issue(self):
        result, api = self.sync(True, [[issue()], issue(), [], issue(), comment(), issue(), issue("closed")])
        self.assertEqual(result, "ISSUE_RECOVERED")
        self.assertEqual(next(call for call in api.call_args_list if call.args[1] == "POST").args[1:3], ("POST", notices.REPO_PATH + "/issues/1/comments"))
        self.assertEqual(next(call for call in api.call_args_list if call.args[1] == "POST").kwargs["payload"], {"body": notices.recovery_body("55-1")})
        self.assertEqual(api.call_args.kwargs["payload"], {"state": "closed", "state_reason": "completed"})

    def test_close_retry_does_not_repeat_comment_and_old_cycle_does_not_suppress_new(self):
        with patch.object(notices, "api_request", side_effect=[[issue()], issue(), [], issue(), comment(), issue(), notices.NotificationError()]):
            with self.assertRaises(notices.NotificationError):
                notices.sync_incident(True)
        result, api = self.sync(True, [[issue()], issue(), [comment()], issue(), issue("closed")])
        self.assertEqual(result, "ISSUE_RECOVERED")
        self.assertFalse(any(call.args[1] == "POST" for call in api.call_args_list))
        result, api = self.sync(True, [[issue(cycle="77-1")], issue(cycle="77-1"), [comment()],
                                      issue(cycle="77-1"), comment("77-1"), issue(cycle="77-1"), issue("closed", cycle="77-1")])
        self.assertEqual(result, "ISSUE_RECOVERED")
        self.assertEqual(next(call for call in api.call_args_list if call.args[1] == "POST").kwargs["payload"]["body"], notices.recovery_body("77-1"))

    def test_only_owned_issue_is_considered_and_damaged_ownership_blocks_mutation(self):
        unrelated = issue()
        unrelated["user"] = {"login": "someone-else", "type": "User"}
        result, api = self.sync(True, [[unrelated]])
        self.assertEqual(result, "NO_OPEN_INCIDENT")
        self.assertEqual(api.call_count, 1)
        changes = [{"assignees": [{"login": "someone-else"}]},
                   {"assignees": [{"login": "Kanshikun"}, {"login": "someone-else"}]},
                   {"repository_url": "https://api.github.com/repos/other/repo"},
                   {"body": "removed-marker"}, {"title": "renamed dedicated issue"}, {"pull_request": {}}, {"number": True}]
        for change in changes:
            with self.subTest(change=list(change)):
                malformed = {**issue(), **change}
                with patch.object(notices, "api_request", return_value=[malformed]) as api:
                    with self.assertRaises(notices.NotificationError):
                        notices.sync_incident(True)
                self.assertEqual(api.call_count, 1)

    def test_rerunning_same_workflow_has_a_new_incident_cycle(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}):
            result, api = self.sync(False, [[issue("closed", "77-1")], issue("closed", "77-1"),
                                            issue(cycle="77-2")])
        self.assertEqual(result, "ISSUE_REOPENED")
        self.assertEqual(api.call_args.kwargs["payload"]["body"], notices.outage_body("77-2"))
        result, api = self.sync(True, [[issue(cycle="77-2")], issue(cycle="77-2"), [comment("77-1")],
                                      issue(cycle="77-2"), comment("77-2"), issue(cycle="77-2"),
                                      issue("closed", cycle="77-2")])
        self.assertEqual(result, "ISSUE_RECOVERED")
        posted = next(call for call in api.call_args_list if call.args[1] == "POST")
        self.assertEqual(posted.kwargs["payload"]["body"], notices.recovery_body("77-2"))

    def test_changed_cycle_during_comment_scan_prevents_post_or_close(self):
        with patch.object(notices, "api_request", side_effect=[[issue()], issue(), [], issue(cycle="88-1")]) as api:
            with self.assertRaises(notices.NotificationError): notices.sync_incident(True)
        self.assertTrue(all(call.args[1] == "GET" for call in api.call_args_list))

    def test_duplicates_and_incomplete_pagination_never_create_or_close(self):
        for responses in ([[issue(), issue(number=2)]],
                          [[{"title": "unrelated", "user": {}}] * 100] * notices.MAX_PAGES):
            with patch.object(notices, "api_request", side_effect=responses) as api:
                with self.assertRaises(notices.NotificationError):
                    notices.sync_incident(False)
            self.assertTrue(all(call.args[1] == "GET" for call in api.call_args_list))

    def test_context_must_be_this_repository_with_builtin_workflow_environment(self):
        for changed in ({"GH_TOKEN": ""}, {"GITHUB_REPOSITORY": "other/repo"},
                        {"GITHUB_ACTIONS": "false"}, {"GITHUB_RUN_ID": "invalid"}, {"GITHUB_RUN_ATTEMPT": "0"}):
            with self.subTest(changed=list(changed)), patch.dict(os.environ, changed):
                with patch.object(notices, "api_request") as api:
                    with self.assertRaises(notices.NotificationError): notices.sync_incident(False)
                api.assert_not_called()

    def test_official_api_transport_has_no_proxy_redirects_and_bounded_responses(self):
        original = notices.urllib.request.build_opener
        with patch.object(notices.urllib.request, "build_opener", wraps=original) as built:
            with patch.object(notices.urllib.request.OpenerDirector, "open", return_value=Response()) as opened:
                self.assertEqual(notices.api_request(CANARY, "GET", notices.REPO_PATH + "/issues"), [])
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/Kanshikun/public-web-monitor/issues")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + CANARY)
        self.assertIsNone(request.get_header("Cookie"))
        self.assertEqual(opened.call_args.kwargs["timeout"], 10)
        self.assertEqual(built.call_args.args[0].proxies, {})
        self.assertIsNone(notices.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test"))
        for response, error in [(Response(b"x" * (notices.MAX_API_BODY + 1)), None),
                                (Response(CANARY.encode()), None), (None, TimeoutError(CANARY)),
                                (None, urllib.error.HTTPError("https://api.github.com", 302, CANARY, {}, None))]:
            with patch.object(notices.urllib.request.OpenerDirector, "open", return_value=response, side_effect=error):
                with self.assertRaises(notices.NotificationError) as caught:
                    notices.api_request(CANARY, "GET", notices.REPO_PATH + "/issues")
                self.assertNotIn(CANARY, str(caught.exception))

    def test_simulation_notifies_without_site_requests_and_api_failure_is_safe(self):
        output = io.StringIO()
        with patch.object(monitor, "check_target", side_effect=AssertionError("No site requests")):
            with patch.object(monitor, "sync_incident", return_value="ISSUE_CREATED") as sync:
                with redirect_stdout(output):
                    self.assertEqual(monitor.main(["--simulate-failure", "--github-issues"]), 1)
        sync.assert_called_once_with(False)
        self.assertIn("NOTICE monitor ISSUE_CREATED", output.getvalue())
        output = io.StringIO()
        with patch.object(monitor, "sync_incident", side_effect=notices.NotificationError(CANARY)):
            with redirect_stdout(output):
                self.assertEqual(monitor.main(["--simulate-failure", "--github-issues"]), 1)
        self.assertIn("ISSUE_NOTIFICATION_FAILED", output.getvalue())
        self.assertNotIn(CANARY, output.getvalue())


if __name__ == "__main__":
    unittest.main()
