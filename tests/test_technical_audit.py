"""Offline tests for the technical audit CLI. No network and no extra packages."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from http.client import HTTPMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import technical_audit as audit

HOME = "https://example.com/"
ROBOTS = "https://example.com/robots.txt"
SITEMAP = "https://example.com/sitemap.xml"
HTML = {"Content-Type": "text/html; charset=utf-8"}


class FakeWeb:
    def __init__(self, routes: dict[str, tuple[int, str | bytes, dict[str, str]]]) -> None:
        self.routes = {audit.normalize_url(url): value for url, value in routes.items()}
        self.calls: list[str] = []

    def fetch(self, url: str) -> audit.FetchResult:
        self.calls.append(url)
        key = audit.normalize_url(url)
        if key not in self.routes:
            raise AssertionError(f"unexpected fetch {url}")
        status, body, headers = self.routes[key]
        return audit.FetchResult(status, body, headers, key)


def allow_all_site(pages: dict[str, tuple[int, str | bytes, dict[str, str]]], **extra: tuple[int, str | bytes, dict[str, str]]) -> FakeWeb:
    routes: dict[str, tuple[int, str | bytes, dict[str, str]]] = {
        ROBOTS: (200, "User-agent: *\nDisallow:\n", {"Content-Type": "text/plain"}),
        SITEMAP: (404, "", {"Content-Type": "application/xml"}),
    }
    routes.update(pages)
    routes.update(extra)
    return FakeWeb(routes)


def checks_for(report: dict, url: str) -> set[str]:
    return {item["check"] for item in report["findings"] if item["url"] == url}


def page_by_url(report: dict, url: str) -> dict:
    for page in report["pages"]:
        if page["url"] == url:
            return page
    raise AssertionError(url)


class TechnicalAuditTests(unittest.TestCase):
    def test_cli_writes_report_and_marks_external_sources_not_checked(self) -> None:
        web = FakeWeb({
            ROBOTS: (404, "missing", {"Content-Type": "text/plain"}),
            SITEMAP: (404, "", {"Content-Type": "application/xml"}),
            HOME: (200, "<html><head><title>Home</title></head><body><h1>Home</h1></body></html>", HTML),
        })
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "audit.json")
            code = audit.main(
                ["--site", "https://example.com", "--max-pages", "3", "--output", output],
                fetch=web.fetch,
            )
            self.assertEqual(code, 0)
            report = json.loads(Path(output).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["inputs"]["site"], HOME)
        self.assertEqual(report["inputs"]["max_pages"], 3)
        self.assertEqual(report["inputs"]["output"], output)
        self.assertEqual(
            [(item["check"], item["status"]) for item in report["not_checked"]],
            [("gsc", "not_checked"), ("psi", "not_checked"), ("webmaster", "not_checked")],
        )
        for item in report["not_checked"]:
            self.assertTrue(item["reason"])
        self.assertNotIn("score", report)
        self.assertEqual([page["url"] for page in report["pages"]], [HOME])
        self.assertEqual(page_by_url(report, HOME)["status"], 200)
        self.assertNotIn("https://www.googleapis.com", " ".join(web.calls))

    def test_rejects_non_https_and_bad_limits_without_fetching(self) -> None:
        def fail(url: str) -> audit.FetchResult:
            raise AssertionError(url)

        self.assertEqual(
            audit.main(["--site", "http://example.com", "--max-pages", "1", "--output", "out.json"], fetch=fail),
            2,
        )
        self.assertEqual(
            audit.main(["--site", "https://user:pw@example.com", "--max-pages", "1", "--output", "out.json"], fetch=fail),
            2,
        )
        self.assertEqual(
            audit.main(["--site", "https://example.com", "--max-pages", "0", "--output", "out.json"], fetch=fail),
            2,
        )
        with self.assertRaises(SystemExit):
            audit.main(["--max-pages", "1", "--output", "out.json"], fetch=fail)

    def test_crawl_stays_on_origin_and_stops_at_max_pages(self) -> None:
        home = """
        <html><head><title>Home</title>
        <meta name="description" content="Home page">
        <link rel="canonical" href="https://example.com/">
        </head><body><h1>Home</h1>
        <a href="/a">A</a>
        <a href="/b">B</a>
        <a href="https://evil.test/x">E</a>
        <a href="/c">C</a>
        </body></html>
        """
        web = allow_all_site({
            HOME: (200, home, HTML),
            "https://example.com/a": (200, "<html><head><title>A</title></head><body><h1>A</h1></body></html>", HTML),
        })
        report = audit.audit_site(HOME, 2, web.fetch)
        self.assertEqual(web.calls, [ROBOTS, SITEMAP, HOME, "https://example.com/a"])
        self.assertTrue(report["crawl"]["truncated"])
        self.assertEqual(report["crawl"]["fetched_pages"], 2)

    def test_robots_rules_block_and_specific_agent_can_override(self) -> None:
        robots = "\n".join([
            "User-agent: *",
            "Disallow: /private",
            "Allow: /private/ok",
            "Disallow: /*.pdf$",
            "",
        ])
        home = """
        <html><head><title>Home</title>
        <meta name="description" content="Home">
        <link rel="canonical" href="/"></head><body><h1>Home</h1>
        <a href="/public">Public</a>
        <a href="/private/secret">Secret</a>
        <a href="/private/ok">Ok</a>
        <a href="/files/a.pdf">PDF</a>
        <a href="/files/note.html">Note</a>
        </body></html>
        """
        pages = {
            HOME: (200, home, HTML),
            "https://example.com/public": (200, "<html><title>P</title><body><h1>P</h1></html>", HTML),
            "https://example.com/private/ok": (200, "<html><title>Ok</title><body><h1>Ok</h1></html>", HTML),
            "https://example.com/files/note.html": (200, "<html><title>N</title><body><h1>N</h1></html>", HTML),
        }
        web = allow_all_site(pages)
        web.routes[ROBOTS] = (200, robots, {"Content-Type": "text/plain"})
        report = audit.audit_site(HOME, 10, web.fetch)
        self.assertEqual(web.calls, [
            ROBOTS,
            SITEMAP,
            HOME,
            "https://example.com/public",
            "https://example.com/private/ok",
            "https://example.com/files/note.html",
        ])
        blocked = {item["url"] for item in report["robots"]["blocked"]}
        self.assertEqual(blocked, {
            "https://example.com/private/secret",
            "https://example.com/files/a.pdf",
        })

        closed = FakeWeb({
            ROBOTS: (200, "User-agent: *\nDisallow: /\n", {"Content-Type": "text/plain"}),
            HOME: (200, "<html><title>Home</title></html>", HTML),
        })
        closed_report = audit.audit_site(HOME, 5, closed.fetch)
        self.assertEqual(closed.calls, [ROBOTS])
        self.assertEqual(closed_report["pages"], [])
        self.assertIn(HOME, [item["url"] for item in closed_report["robots"]["blocked"]])

        override = FakeWeb({
            ROBOTS: (
                200,
                "User-agent: *\nDisallow: /\n\nUser-agent: seo-technical-audit\nDisallow:\n",
                {"Content-Type": "text/plain"},
            ),
            SITEMAP: (404, "", {"Content-Type": "application/xml"}),
            HOME: (200, "<html><title>Home</title><body><h1>Home</h1></html>", HTML),
        })
        override_report = audit.audit_site("https://example.com", 2, override.fetch)
        self.assertIn(HOME, [page["url"] for page in override_report["pages"]])

        unavailable = FakeWeb({
            ROBOTS: (503, "down", {"Content-Type": "text/plain"}),
            HOME: (200, "<html><title>Home</title></html>", HTML),
        })
        unavailable_report = audit.audit_site(HOME, 3, unavailable.fetch)
        self.assertEqual(unavailable.calls, [ROBOTS])
        self.assertEqual(unavailable_report["pages"], [])
        self.assertIn("503", unavailable_report["crawl"]["skipped_reason"])

    def test_sitemap_index_adds_same_origin_urls_only(self) -> None:
        index = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/child.xml</loc></sitemap>
        </sitemapindex>
        """
        child = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/from-map</loc></url>
          <url><loc>https://other.example/out</loc></url>
        </urlset>
        """
        robots = "User-agent: *\nDisallow:\nSitemap: https://example.com/sitemap.xml\n"
        mapped = """
        <html><head><title>Mapped</title>
        <meta name="description" content="Mapped page">
        <link rel="canonical" href="https://example.com/from-map">
        </head><body><h1>Mapped</h1></body></html>
        """
        web = FakeWeb({
            ROBOTS: (200, robots, {"Content-Type": "text/plain"}),
            SITEMAP: (200, index, {"Content-Type": "application/xml"}),
            "https://example.com/child.xml": (200, child, {"Content-Type": "application/xml"}),
            HOME: (200, "<html><head><title>Home</title><meta name='description' content='Home'><link rel='canonical' href='/'></head><body><h1>Home</h1></body></html>", HTML),
            "https://example.com/from-map": (200, mapped, HTML),
        })
        report = audit.audit_site(HOME, 5, web.fetch)
        self.assertEqual(
            [doc["type"] for doc in report["sitemap"]["documents"]],
            ["sitemapindex", "urlset"],
        )
        self.assertEqual(report["sitemap"]["urls"], ["https://example.com/from-map"])
        self.assertEqual(report["sitemap"]["off_origin_urls"], ["https://other.example/out"])
        self.assertEqual(
            [page["url"] for page in report["pages"]],
            [HOME, "https://example.com/from-map"],
        )
        self.assertNotIn("https://other.example/out", web.calls)

    def test_on_page_signals_title_description_h1_canonical_and_noindex(self) -> None:
        home = """
        <html><head>
        <title>Tom &amp; Jerry</title>
        <meta name="description" content="Cartoon pair">
        <link rel="canonical" href="/home">
        </head><body><h1>Main <span>show</span></h1>
        <a href="/bad">Bad</a>
        <a href="/multi">Multi</a>
        <a href="/cross">Cross</a>
        <a href="/quiet">Quiet</a>
        <a href="/hdr">Hdr</a>
        </body></html>
        """
        bad = "<html><head><meta property='og:description' content='OG only'></head><body></body></html>"
        multi = """
        <html><head><title>Multi</title>
        <meta name="description" content="Has description">
        <link rel="canonical" href="https://example.com/multi">
        </head><body><h1>A</h1><h1>B</h1></body></html>
        """
        cross = """
        <html><head><title>Cross</title>
        <meta name="description" content="Cross">
        <link rel="canonical" href="https://other.example/x">
        </head><body><h1>Cross</h1></body></html>
        """
        quiet = """
        <html><head><title>Quiet</title>
        <meta name="description" content="Quiet">
        <meta name="robots" content="noindex, nofollow">
        <link rel="canonical" href="https://example.com/quiet">
        </head><body><h1>Quiet</h1></body></html>
        """
        hdr = """
        <html><head><title>Hdr</title>
        <meta name="description" content="Hdr">
        <link rel="canonical" href="https://example.com/hdr">
        </head><body><h1>Hdr</h1></body></html>
        """
        web = allow_all_site({
            HOME: (200, home, HTML),
            "https://example.com/bad": (200, bad, HTML),
            "https://example.com/multi": (200, multi, HTML),
            "https://example.com/cross": (200, cross, HTML),
            "https://example.com/quiet": (200, quiet, HTML),
            "https://example.com/hdr": (200, hdr, {"Content-Type": "text/html", "X-Robots-Tag": "none"}),
        })
        report = audit.audit_site(HOME, 10, web.fetch)
        home_page = page_by_url(report, HOME)
        self.assertEqual(home_page["title"], "Tom & Jerry")
        self.assertEqual(home_page["description"], "Cartoon pair")
        self.assertEqual(home_page["h1"], ["Main show"])
        self.assertEqual(home_page["canonical"], "https://example.com/home")
        self.assertFalse(home_page["noindex"])
        self.assertEqual(checks_for(report, HOME), set())
        self.assertEqual(
            checks_for(report, "https://example.com/bad"),
            {"missing_title", "missing_description", "missing_h1", "missing_canonical"},
        )
        self.assertEqual(checks_for(report, "https://example.com/multi"), {"multiple_h1"})
        self.assertEqual(checks_for(report, "https://example.com/cross"), {"canonical_cross_origin"})
        self.assertEqual(page_by_url(report, "https://example.com/cross")["canonical"], "https://other.example/x")
        self.assertTrue(page_by_url(report, "https://example.com/quiet")["noindex"])
        self.assertEqual(checks_for(report, "https://example.com/quiet"), {"noindex"})
        self.assertTrue(page_by_url(report, "https://example.com/hdr")["noindex"])
        self.assertEqual(checks_for(report, "https://example.com/hdr"), {"noindex"})

    def test_missing_alt_and_internal_404_need_a_real_response(self) -> None:
        home = """
        <html><head><title>Home</title>
        <meta name="description" content="Home">
        <link rel="canonical" href="https://example.com/">
        </head><body><h1>Home</h1>
        <img src="/ok.png" alt="Ok">
        <img src="/empty.png" alt="">
        <img src="/missing.png">
        <img src="also.png">
        <a href="/gone">Gone</a>
        <a href="https://evil.test/missing">Evil</a>
        </body></html>
        """
        web = allow_all_site({
            HOME: (200, home, HTML),
            "https://example.com/gone": (404, "missing", {"Content-Type": "text/html"}),
        })
        report = audit.audit_site(HOME, 5, web.fetch)
        self.assertEqual(page_by_url(report, HOME)["missing_alt"], [
            {"src": "https://example.com/missing.png"},
            {"src": "https://example.com/also.png"},
        ])
        self.assertEqual(checks_for(report, HOME), {"missing_alt"})
        self.assertEqual(report["internal_404"], [
            {"to": "https://example.com/gone", "status": 404, "from": [HOME]},
        ])
        self.assertEqual(checks_for(report, "https://example.com/gone"), {"internal_404"})
        self.assertEqual(page_by_url(report, "https://example.com/gone")["status"], 404)
        self.assertNotIn("https://evil.test/missing", web.calls)
        self.assertNotIn("https://example.com/missing.png", web.calls)

        capped = allow_all_site({
            HOME: (200, home, HTML),
        })
        capped_report = audit.audit_site(HOME, 1, capped.fetch)
        self.assertEqual(capped_report["internal_404"], [])
        self.assertNotIn("https://example.com/gone", capped.calls)

    def test_redirect_handler_does_not_request_other_origins(self) -> None:
        class StopOpen:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def open(self, req: urllib.request.Request, timeout: float | None = None) -> str:
                self.urls.append(req.full_url)
                return "stopped"

        class Body:
            def __init__(self) -> None:
                self.reads = 0

            def read(self, amount: int = -1) -> bytes:
                self.reads += 1
                return b""

            def close(self) -> None:
                return None

        def location(value: str) -> HTTPMessage:
            headers = HTTPMessage()
            headers["Location"] = value
            return headers

        handler = audit.SameOriginRedirectHandler()
        opener = StopOpen()
        handler.parent = opener
        request = urllib.request.Request("https://example.com/start")
        request.timeout = 15

        for target in ("https://evil.test/collect", "//evil.test/path", "https://127.0.0.1/secret"):
            body = Body()
            with self.assertRaises(urllib.error.HTTPError) as caught:
                handler.http_error_302(request, body, 302, "Found", location(target))
            self.assertEqual(caught.exception.url, "https://example.com/start")
            self.assertEqual(body.reads, 0)
            self.assertEqual(opener.urls, [])

        body = Body()
        result = handler.http_error_302(
            request, body, 302, "Found", location("https://example.com/next")
        )
        self.assertEqual(result, "stopped")
        self.assertEqual(opener.urls, ["https://example.com/next"])
        self.assertEqual(body.reads, 1)

    def test_rejects_localhost_and_private_targets_without_fetching(self) -> None:
        def fail(url: str) -> audit.FetchResult:
            raise AssertionError(url)

        blocked = [
            "https://localhost",
            "https://localhost:8443/admin",
            "https://foo.localhost/a",
            "https://127.0.0.1/",
            "https://10.1.2.3/page",
            "https://192.168.0.5/",
            "https://172.16.5.5/",
            "https://169.254.1.1/",
            "https://[::1]/",
            "https://[fd00::1]/",
            "https://[::ffff:10.0.0.1]/",
        ]
        for site in blocked:
            self.assertEqual(
                audit.main(["--site", site, "--max-pages", "1", "--output", "out.json"], fetch=fail),
                2,
                site,
            )
            with self.assertRaises(ValueError):
                audit.audit_site(site, 1, fail)
        self.assertEqual(audit.validate_site("https://example.com/path"), "https://example.com/path")
        self.assertEqual(audit.validate_site("https://172.32.0.1/"), "https://172.32.0.1/")
        self.assertEqual(audit.validate_site("https://8.8.8.8/"), "https://8.8.8.8/")
        self.assertEqual(
            audit.main(["--site", "http://127.0.0.1", "--max-pages", "1", "--output", "out.json"], fetch=fail),
            2,
        )

    def test_findings_separate_severity_from_impact(self) -> None:
        home = """
        <html><head>
        <link rel="canonical" href="https://other.example/x">
        </head><body>
        <h1>One</h1><h1>Two</h1>
        <img src="/bare.png">
        <a href="/gone">Gone</a>
        <a href="/down">Down</a>
        <a href="/quiet">Quiet</a>
        </body></html>
        """
        quiet = """
        <html><head><title>Quiet</title>
        <meta name="description" content="Quiet page">
        <meta name="robots" content="noindex">
        <link rel="canonical" href="https://example.com/quiet">
        </head><body><h1>Quiet</h1></body></html>
        """
        web = allow_all_site({
            HOME: (200, home, HTML),
            "https://example.com/gone": (404, "missing", HTML),
            "https://example.com/down": (503, "down", HTML),
            "https://example.com/quiet": (200, quiet, HTML),
        })
        report = audit.audit_site(HOME, 10, web.fetch)
        levels = {"high", "medium", "low"}
        self.assertTrue(report["findings"])
        for item in report["findings"]:
            self.assertIn(item["severity"], levels)
            self.assertNotIn(item["impact"].strip().lower(), levels)
            self.assertGreaterEqual(len(item["impact"].split()), 4)
        expected = {
            "missing_title": "high",
            "missing_description": "medium",
            "multiple_h1": "low",
            "canonical_cross_origin": "high",
            "missing_alt": "low",
            "internal_404": "high",
            "noindex": "high",
        }
        seen = {item["check"]: item["severity"] for item in report["findings"]}
        for check, severity in expected.items():
            self.assertEqual(seen[check], severity, check)
        down = next(item for item in report["findings"] if item["url"] == "https://example.com/down")
        self.assertEqual(down["check"], "http_status")
        self.assertEqual(down["severity"], "high")
        self.assertIn("server", down["impact"].lower())

    def test_unavailable_robots_blocks_on_page_crawl(self) -> None:
        unavailable = FakeWeb({
            ROBOTS: (503, "down", {"Content-Type": "text/plain"}),
            HOME: (200, "<html><title>Home</title></html>", HTML),
        })
        report = audit.audit_site(HOME, 3, unavailable.fetch)
        self.assertEqual(unavailable.calls, [ROBOTS])
        self.assertEqual(report["pages"], [])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["crawl"]["status"], "not_checked")
        self.assertIn("503", report["crawl"]["reason"])
        on_page = [item for item in report["not_checked"] if item["check"] == "on_page"]
        self.assertEqual(len(on_page), 1)
        self.assertEqual(on_page[0]["status"], "not_checked")
        self.assertIn("503", on_page[0]["reason"])
        self.assertNotIn(
            ("on_page", "completed"),
            [(item["check"], item["status"]) for item in report["not_checked"]],
        )

    def test_yadro_redirect_to_login_is_not_scored_as_the_requested_url(self) -> None:
        yadro = "https://example.com/yadro"
        login = "https://example.com/login"
        login_html = """
        <html><head>
        <meta name="robots" content="noindex, nofollow">
        </head><body><h1>Login</h1></body></html>
        """

        def site() -> tuple[FakeWeb, object]:
            web = allow_all_site({
                yadro: (200, login_html, HTML),
                login: (200, login_html, HTML),
            })

            def fetch(url: str) -> audit.FetchResult:
                result = web.fetch(url)
                if audit.normalize_url(url) == yadro:
                    result.final_url = login
                return result

            return web, fetch

        web, fetch = site()
        report = audit.audit_site(yadro, 2, fetch)
        self.assertEqual(web.calls, [ROBOTS, SITEMAP, yadro, login])
        yadro_page = page_by_url(report, yadro)
        login_page = page_by_url(report, login)
        self.assertEqual(yadro_page["requested_url"], yadro)
        self.assertEqual(yadro_page["final_url"], login)
        self.assertNotEqual(yadro_page["requested_url"], yadro_page["final_url"])
        self.assertEqual(yadro_page["url"], yadro)
        self.assertFalse(yadro_page["noindex"])
        self.assertIsNone(yadro_page["canonical"])
        self.assertEqual(yadro_page["title"], "")
        self.assertEqual(checks_for(report, yadro), {"redirect"})
        redirect = next(item for item in report["findings"] if item["url"] == yadro)
        self.assertEqual(redirect["check"], "redirect")
        self.assertIn(login, redirect["observation"])
        self.assertEqual(login_page["requested_url"], login)
        self.assertEqual(login_page["final_url"], login)
        self.assertTrue(login_page["noindex"])
        self.assertEqual(
            checks_for(report, login),
            {"missing_title", "missing_description", "missing_canonical", "noindex"},
        )

        capped_web, capped_fetch = site()
        capped = audit.audit_site(yadro, 1, capped_fetch)
        self.assertEqual([page["url"] for page in capped["pages"]], [yadro])
        self.assertEqual(capped_web.calls, [ROBOTS, SITEMAP, yadro])
        self.assertEqual(checks_for(capped, yadro), {"redirect"})
        self.assertFalse(any(item["check"] in {"noindex", "missing_canonical", "missing_title"} for item in capped["findings"]))


if __name__ == "__main__":
    unittest.main()
