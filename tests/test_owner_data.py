"""Offline tests for the owner-data collector. No network and no extra packages."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import owner_data as owner

METRIKA_TOKEN = "metrika-secret-token-value"
WEBMASTER_TOKEN = "webmaster-secret-token-value"
GSC_TOKEN = "gsc-secret-token-value"
TOKENS = (METRIKA_TOKEN, WEBMASTER_TOKEN, GSC_TOKEN)
ENV = {
    "YANDEX_METRIKA_TOKEN": METRIKA_TOKEN,
    "YANDEX_WEBMASTER_TOKEN": WEBMASTER_TOKEN,
    "GSC_ACCESS_TOKEN": GSC_TOKEN,
}
NOW = "2026-10-13T12:00:00Z"
HOST_ID = "https:example.com:443"
HOST_PATH = "/v4/user/9/hosts/https%3Aexample.com%3A443"
GSC_QUERY = "/webmasters/v3/sites/sc-domain%3Aexample.com/searchAnalytics/query"


def route_key(request: owner.HttpRequest) -> str:
    parts = urlsplit(request.url)
    if parts.path == "/stat/v1/data":
        metrics = parse_qs(parts.query).get("metrics", [""])[0]
        kind = "goals" if "goal" in metrics else "organic"
        return f"GET {parts.path} {kind}"
    if request.method == "POST" and parts.path.endswith("/searchAnalytics/query"):
        body = json.loads(request.body or b"{}")
        kind = "queries" if "dimensions" in body else "totals"
        return f"POST {parts.path} {kind}"
    return f"{request.method} {parts.path}"


class FakeApi:
    def __init__(self, routes: dict[str, tuple[int, dict]]) -> None:
        self.routes = routes
        self.calls: list[owner.HttpRequest] = []

    def __call__(self, request: owner.HttpRequest) -> owner.HttpResponse:
        self.calls.append(request)
        key = route_key(request)
        if key not in self.routes:
            raise AssertionError(f"unexpected {key}")
        status, payload = self.routes[key]
        return owner.HttpResponse(status, json.dumps(payload).encode("utf-8"), None)


def success_routes() -> dict[str, tuple[int, dict]]:
    return {
        "GET /management/v1/counter/100": (200, {"id": 100, "site": "example.com"}),
        "GET /stat/v1/data organic": (
            200,
            {
                "sampled": False,
                "total_rows": 1,
                "totals": [12, 4],
                "data": [{"dimensions": [{"name": "Google"}], "metrics": [12, 4]}],
            },
        ),
        "GET /management/v1/counter/100/goals": (
            200,
            {"goals": [{"id": 7, "name": "Заявка", "type": "action"}]},
        ),
        "GET /stat/v1/data goals": (200, {"totals": [3]}),
        "GET /v4/user": (200, {"user_id": 9}),
        "GET /v4/user/9/hosts": (
            200,
            {
                "hosts": [
                    {
                        "host_id": HOST_ID,
                        "ascii_host_url": "https://example.com/",
                        "unicode_host_url": "https://example.com/",
                        "verified": True,
                    }
                ]
            },
        ),
        f"GET {HOST_PATH}/summary": (
            200,
            {"sqi": 10, "searchable_pages_count": 4, "excluded_pages_count": 1},
        ),
        f"GET {HOST_PATH}/diagnostics": (
            200,
            {"problems": {"NO_SITEMAP": {"severity": "FATAL", "state": "PRESENT"}}},
        ),
        "GET /webmasters/v3/sites": (
            200,
            {"siteEntry": [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}]},
        ),
        f"POST {GSC_QUERY} totals": (
            200,
            {"rows": [{"clicks": 5, "impressions": 50, "ctr": 0.1, "position": 8.5}]},
        ),
        f"POST {GSC_QUERY} queries": (
            200,
            {"rows": [{"keys": ["example query"], "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 4}]},
        ),
    }


def args(output: str) -> list[str]:
    return [
        "--site",
        "https://example.com",
        "--date1",
        "2026-09-12",
        "--date2",
        "2026-10-11",
        "--metrika-counter",
        "100",
        "--gsc-property",
        "sc-domain:example.com",
        "--output",
        output,
    ]


def required_args(output: str) -> list[str]:
    return [
        "--site",
        "https://example.com",
        "--date1",
        "2026-09-12",
        "--date2",
        "2026-10-11",
        "--output",
        output,
    ]


def run(argv: list[str], transport, env: dict | None) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = owner.main(argv, transport=transport, now=lambda: NOW, env=env)
    return code, stdout.getvalue(), stderr.getvalue()


def assert_no_secrets(testcase: unittest.TestCase, *chunks: str) -> None:
    for chunk in chunks:
        for secret in TOKENS:
            testcase.assertNotIn(secret, chunk)
        testcase.assertNotIn("Authorization", chunk)


class OwnerDataTests(unittest.TestCase):
    def test_output_parent_is_created_for_a_new_client_run(self) -> None:
        def transport(request: owner.HttpRequest) -> owner.HttpResponse:
            raise AssertionError(request.url)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "runs" / "client" / "owner-data.json"
            code, stdout, stderr = run(required_args(str(output)), transport, {})
            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            self.assertTrue(output.is_file())

    def test_success_collects_bounded_reports_after_exact_match(self) -> None:
        api = FakeApi(success_routes())
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, stdout, stderr = run(args(output), api, ENV)
            text = Path(output).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        assert_no_secrets(self, text)
        report = json.loads(text)
        self.assertEqual(report["agent"], "owner_data")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["checked_at"], NOW)
        self.assertEqual(report["inputs"]["site"], "https://example.com/")
        self.assertEqual(report["inputs"]["date1"], "2026-09-12")
        self.assertEqual(report["inputs"]["date2"], "2026-10-11")
        self.assertEqual([item["source"] for item in report["sources"]], ["yandex_metrika", "yandex_webmaster", "gsc"])
        metrika, webmaster, gsc = report["sources"]
        for item in report["sources"]:
            self.assertEqual(item["period"], {"date1": "2026-09-12", "date2": "2026-10-11"})
            self.assertEqual(item["checked_at"], NOW)
            self.assertEqual(item["status"], "ready")
            self.assertIsNone(item["reason"])
            self.assertIsNone(item["quota"])
        self.assertEqual(metrika["property"], "100")
        self.assertEqual(metrika["counts"]["organic_visits"], 12)
        self.assertEqual(metrika["counts"]["organic_users"], 4)
        self.assertEqual(metrika["counts"]["goals"], 1)
        self.assertEqual(metrika["counts"]["goal_reaches"], 3)
        self.assertEqual(metrika["counts"]["rows"], 1)
        self.assertEqual(metrika["data"]["goals"][0]["reaches"], 3)
        self.assertEqual(webmaster["property"], HOST_ID)
        self.assertEqual(webmaster["counts"]["problems"], 1)
        self.assertEqual(webmaster["counts"]["summary_fields"], 3)
        self.assertEqual(webmaster["data"]["summary_scope"], "current")
        self.assertEqual(gsc["property"], "sc-domain:example.com")
        self.assertEqual(gsc["counts"], {"rows": 1, "clicks": 5, "impressions": 50})
        self.assertEqual(gsc["data"]["queries"][0]["query"], "example query")
        keys = [route_key(call) for call in api.calls]
        self.assertLess(keys.index("GET /management/v1/counter/100"), keys.index("GET /stat/v1/data organic"))
        self.assertLess(keys.index("GET /webmasters/v3/sites"), keys.index(f"POST {GSC_QUERY} totals"))
        self.assertLess(keys.index("GET /v4/user/9/hosts"), keys.index(f"GET {HOST_PATH}/diagnostics"))
        for call in api.calls:
            self.assertNotIn("secret", call.url)
            self.assertTrue(call.headers["Authorization"].startswith(("OAuth ", "Bearer ")))
        self.assertTrue(api.calls[0].headers["Authorization"].endswith(METRIKA_TOKEN))
        self.assertTrue(any(call.headers["Authorization"].endswith(GSC_TOKEN) for call in api.calls))

    def test_missing_tokens_are_not_checked_and_do_not_call_network(self) -> None:
        def transport(request: owner.HttpRequest) -> owner.HttpResponse:
            raise AssertionError(request.url)

        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, stdout, stderr = run(args(output), transport, {})
            report = json.loads(Path(output).read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertEqual(report["status"], "needs_input")
        self.assertEqual(
            [item["status"] for item in report["sources"]],
            ["not_checked", "not_checked", "not_checked"],
        )
        reasons = " ".join(item["reason"] for item in report["sources"])
        self.assertIn("YANDEX_METRIKA_TOKEN", reasons)
        self.assertIn("YANDEX_WEBMASTER_TOKEN", reasons)
        self.assertIn("GSC_ACCESS_TOKEN", reasons)
        for item in report["sources"]:
            self.assertIsNone(item["counts"])
            self.assertIsNone(item["data"])
            self.assertTrue(item["reason"])

    def test_metrika_only_collects_and_skips_gsc(self) -> None:
        routes = {key: value for key, value in success_routes().items() if "webmasters" not in key}
        api = FakeApi(routes)
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, stdout, stderr = run(required_args(output) + ["--metrika-counter", "100"], api, ENV)
            text = Path(output).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        assert_no_secrets(self, text)
        report = json.loads(text)
        metrika, webmaster, gsc = report["sources"]
        self.assertEqual(report["status"], "needs_input")
        self.assertEqual(report["inputs"]["metrika_counter"], "100")
        self.assertIsNone(report["inputs"]["gsc_property"])
        self.assertEqual(metrika["status"], "ready")
        self.assertEqual(webmaster["status"], "ready")
        self.assertEqual(gsc["status"], "not_checked")
        self.assertIsNone(gsc["property"])
        self.assertIsNone(gsc["counts"])
        self.assertIsNone(gsc["data"])
        self.assertIn("--gsc-property", gsc["reason"])
        self.assertFalse(any("webmasters" in call.url or "searchAnalytics" in call.url for call in api.calls))

    def test_gsc_only_collects_and_skips_metrika(self) -> None:
        routes = {
            key: value
            for key, value in success_routes().items()
            if not key.startswith("GET /management") and not key.startswith("GET /stat")
        }
        api = FakeApi(routes)
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, stdout, stderr = run(required_args(output) + ["--gsc-property", "sc-domain:example.com"], api, ENV)
            text = Path(output).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        assert_no_secrets(self, text)
        report = json.loads(text)
        metrika, webmaster, gsc = report["sources"]
        self.assertEqual(report["status"], "needs_input")
        self.assertIsNone(report["inputs"]["metrika_counter"])
        self.assertEqual(report["inputs"]["gsc_property"], "sc-domain:example.com")
        self.assertEqual(metrika["status"], "not_checked")
        self.assertIsNone(metrika["property"])
        self.assertIsNone(metrika["counts"])
        self.assertIsNone(metrika["data"])
        self.assertIn("--metrika-counter", metrika["reason"])
        self.assertEqual(webmaster["status"], "ready")
        self.assertEqual(gsc["status"], "ready")
        self.assertFalse(any("api-metrika" in call.url for call in api.calls))

    def test_missing_identifiers_skip_both_private_panels(self) -> None:
        routes = {key: value for key, value in success_routes().items() if key.startswith("GET /v4/user")}
        api = FakeApi(routes)
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, stdout, stderr = run(required_args(output), api, ENV)
            text = Path(output).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        assert_no_secrets(self, text)
        report = json.loads(text)
        metrika, webmaster, gsc = report["sources"]
        self.assertEqual(report["status"], "needs_input")
        self.assertIsNone(report["inputs"]["metrika_counter"])
        self.assertIsNone(report["inputs"]["gsc_property"])
        self.assertEqual(metrika["status"], "not_checked")
        self.assertEqual(gsc["status"], "not_checked")
        self.assertIsNone(metrika["property"])
        self.assertIsNone(gsc["property"])
        self.assertIsNone(metrika["counts"])
        self.assertIsNone(gsc["counts"])
        self.assertIsNone(metrika["data"])
        self.assertIsNone(gsc["data"])
        self.assertIn("--metrika-counter", metrika["reason"])
        self.assertIn("--gsc-property", gsc["reason"])
        self.assertEqual(webmaster["status"], "ready")
        self.assertFalse(any("api-metrika" in call.url or "webmasters" in call.url for call in api.calls))

    def test_supplied_identifiers_are_still_validated(self) -> None:
        def transport(request: owner.HttpRequest) -> owner.HttpResponse:
            raise AssertionError(request.url)

        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            base = required_args(output)
            self.assertEqual(run(base + ["--metrika-counter", "0"], transport, {})[0], 2)
            self.assertEqual(run(base + ["--metrika-counter", "abc"], transport, {})[0], 2)
            self.assertEqual(run(base + ["--metrika-counter", ""], transport, {})[0], 2)
            self.assertEqual(run(base + ["--gsc-property", "not-a-property"], transport, {})[0], 2)
            self.assertEqual(run(base + ["--gsc-property", ""], transport, {})[0], 2)

    def test_wrong_property_skips_private_reports(self) -> None:
        api = FakeApi(
            {
                "GET /management/v1/counter/100": (200, {"id": 100, "site": "other.example"}),
                "GET /v4/user": (200, {"user_id": 9}),
                "GET /v4/user/9/hosts": (
                    200,
                    {
                        "hosts": [
                            {
                                "host_id": "https:other.example:443",
                                "ascii_host_url": "https://other.example/",
                                "verified": True,
                            }
                        ]
                    },
                ),
                "GET /webmasters/v3/sites": (
                    200,
                    {"siteEntry": [{"siteUrl": "https://other.example/", "permissionLevel": "siteOwner"}]},
                ),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, _stdout, stderr = run(args(output), api, ENV)
            text = Path(output).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        assert_no_secrets(self, text)
        report = json.loads(text)
        self.assertEqual(report["status"], "needs_input")
        self.assertEqual([item["status"] for item in report["sources"]], ["not_checked", "not_checked", "not_checked"])
        self.assertIn("не совпадает", report["sources"][0]["reason"])
        self.assertIn("отсутствует", report["sources"][1]["reason"])
        self.assertIn("отсутствует", report["sources"][2]["reason"])
        for item in report["sources"]:
            self.assertIsNone(item["counts"])
            self.assertIsNone(item["data"])
        called = {route_key(call) for call in api.calls}
        self.assertNotIn("GET /stat/v1/data organic", called)
        self.assertNotIn("GET /stat/v1/data goals", called)
        self.assertFalse(any(key.endswith("/summary") or key.endswith("/diagnostics") for key in called))
        self.assertFalse(any("searchAnalytics" in key for key in called))

    def test_api_error_is_failed_and_redacts_tokens(self) -> None:
        def transport(request: owner.HttpRequest) -> owner.HttpResponse:
            if "api-metrika" in request.url:
                return owner.HttpResponse(0, b"", f"timeout {METRIKA_TOKEN}")
            body = json.dumps({"error": f"{WEBMASTER_TOKEN} and {GSC_TOKEN} leaked"}).encode("utf-8")
            return owner.HttpResponse(500, body, None)

        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, stdout, stderr = run(args(output), transport, ENV)
            text = Path(output).read_text(encoding="utf-8")
        self.assertEqual(code, owner.EXIT_FAILED)
        self.assertNotEqual(code, 0)
        assert_no_secrets(self, text, stdout, stderr)
        self.assertIn("[redacted]", text)
        self.assertIn("[redacted]", stderr)
        report = json.loads(text)
        self.assertEqual(report["status"], "failed")
        for item in report["sources"]:
            self.assertEqual(item["status"], "failed")
            self.assertIsNone(item["counts"])
            self.assertIsNone(item["data"])
            self.assertNotIn("0 визит", item["reason"])
            for secret in TOKENS:
                self.assertNotIn(secret, item["reason"])

    def test_forbidden_access_is_not_checked_without_private_report(self) -> None:
        def transport(request: owner.HttpRequest) -> owner.HttpResponse:
            if request.url.endswith("/counter/100") or request.url.endswith("/v4/user") or request.url.endswith("/sites"):
                return owner.HttpResponse(403, b'{"error":"forbidden"}', None)
            raise AssertionError(request.url)

        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, _stdout, _stderr = run(args(output), transport, ENV)
            report = json.loads(Path(output).read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "needs_input")
        self.assertTrue(all(item["status"] == "not_checked" for item in report["sources"]))
        self.assertTrue(all(item["counts"] is None for item in report["sources"]))

    def test_rejects_bad_arguments_without_requests(self) -> None:
        def transport(request: owner.HttpRequest) -> owner.HttpResponse:
            raise AssertionError(request.url)

        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            base = args(output)
            self.assertEqual(run(["--site", "http://example.com", *base[2:]], transport, {})[0], 2)
            replaced = base.copy()
            replaced[replaced.index("--date2") + 1] = "2026-01-01"
            self.assertEqual(run(replaced, transport, {})[0], 2)
            private = base.copy()
            private[1] = "https://127.0.0.1/"
            self.assertEqual(run(private, transport, {})[0], 2)
            bad_gsc = base.copy()
            bad_gsc[bad_gsc.index("--gsc-property") + 1] = "not-a-property"
            self.assertEqual(run(bad_gsc, transport, {})[0], 2)
            code, stdout, stderr = run(base + ["--access-token", METRIKA_TOKEN], transport, {})
            self.assertEqual(code, 2)
            assert_no_secrets(self, stdout, stderr)
            self.assertIn("environment", stderr)
        with self.assertRaises(SystemExit) as raised:
            with contextlib.redirect_stderr(io.StringIO()):
                owner.main(["--output", "x.json"], transport=transport, env={})
        self.assertEqual(raised.exception.code, 2)

    def test_transport_refuses_unlisted_host_without_opening_it(self) -> None:
        response = owner.default_transport(owner.HttpRequest("GET", "https://evil.example/secret", {}, None))
        self.assertEqual(response.status, 0)
        self.assertEqual(response.error, "request host is not allowed")
        self.assertNotIn(METRIKA_TOKEN, response.error or "")

    def test_network_exception_is_redacted(self) -> None:
        def transport(request: owner.HttpRequest) -> owner.HttpResponse:
            raise urllib.error.URLError(METRIKA_TOKEN)

        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "owner-data.json")
            code, stdout, stderr = run(args(output), transport, ENV)
            text = Path(output).read_text(encoding="utf-8")
        self.assertEqual(code, owner.EXIT_FAILED)
        assert_no_secrets(self, text, stdout, stderr)
        report = json.loads(text)
        self.assertTrue(all(item["counts"] is None for item in report["sources"]))


class SchemaTests(unittest.TestCase):
    def test_schema_file_is_json_and_names_the_report(self) -> None:
        path = Path(__file__).resolve().parents[1] / "contracts" / "owner-data.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["agent"]["const"], "owner_data")
        self.assertIn("source", schema["$defs"]["source"]["required"])
        self.assertIn("counts", schema["$defs"]["source"]["required"])
        self.assertIn("checked_at", schema["required"])

    def test_schema_allows_missing_identifiers_and_requires_property_when_ready(self) -> None:
        path = Path(__file__).resolve().parents[1] / "contracts" / "owner-data.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        inputs = schema["properties"]["inputs"]["properties"]
        self.assertEqual(inputs["metrika_counter"]["type"], ["string", "null"])
        self.assertEqual(inputs["gsc_property"]["type"], ["string", "null"])
        source = schema["$defs"]["source"]
        self.assertEqual(source["properties"]["property"]["type"], ["string", "null"])
        ready_then = source["allOf"][0]["then"]["properties"]
        self.assertEqual(ready_then["property"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
