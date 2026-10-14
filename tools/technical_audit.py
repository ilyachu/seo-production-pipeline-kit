#!/usr/bin/env python3
"""Bounded same-origin technical SEO audit.

Usage:
    python tools/technical_audit.py --site https://example.com/ --max-pages 20 --output audit.json

The report records crawl evidence for robots.txt, sitemap, HTTP status, title,
meta description, H1, canonical, noindex, images without alt, and internal 404s.
Google Search Console, PageSpeed Insights, and Yandex Webmaster are always
``not_checked``: this command does not call them and does not invent their data.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

USER_AGENT = "seo-technical-audit/1.0"
MAX_BYTES = 1_500_000
SITEMAP_URL_CAP = 1000
CHILD_SITEMAP_CAP = 20

NOT_CHECKED = (
    {
        "check": "gsc",
        "label": "Google Search Console",
        "status": "not_checked",
        "reason": "No Search Console credentials in this run. Index coverage and search queries were not read.",
    },
    {
        "check": "psi",
        "label": "PageSpeed Insights",
        "status": "not_checked",
        "reason": "PageSpeed Insights was not called. Core Web Vitals and lab speed were not measured.",
    },
    {
        "check": "webmaster",
        "label": "Yandex Webmaster",
        "status": "not_checked",
        "reason": "No Yandex Webmaster credentials in this run. Indexation and diagnostics were not read.",
    },
)


@dataclass
class FetchResult:
    """One HTTP response. ``status`` 0 means the request did not complete."""

    status: int
    body: bytes = b""
    headers: dict[str, str] | None = None
    final_url: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.body, str):
            self.body = self.body.encode("utf-8")
        self.headers = {str(key).lower(): str(value) for key, value in (self.headers or {}).items()}


@dataclass
class RobotsFile:
    rules: list[tuple[bool, str]] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)


@dataclass
class ParsedPage:
    title: str = ""
    description: str = ""
    h1: list[str] = field(default_factory=list)
    canonical: str | None = None
    noindex: bool = False
    base_href: str | None = None
    images: list[tuple[str, bool]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


class HTMLExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page = ParsedPage()
        self._skip = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style"}:
            self._skip += 1
            return
        if self._skip:
            return
        attr = {key.lower(): "" if value is None else value for key, value in attrs}
        if name == "base" and attr.get("href") and self.page.base_href is None:
            self.page.base_href = attr["href"]
        elif name == "title":
            self._in_title = True
            self._title_parts = []
        elif name == "h1":
            self._in_h1 = True
            self._h1_parts = []
        elif name == "meta":
            meta_name = attr.get("name", "").lower()
            content = attr.get("content", "")
            if meta_name == "description" and not self.page.description:
                self.page.description = clean_text(content)
            if meta_name in {"robots", "googlebot", "bingbot"} and directive_noindex(content):
                self.page.noindex = True
        elif name == "link":
            rel = set(attr.get("rel", "").lower().split())
            if "canonical" in rel and self.page.canonical is None:
                self.page.canonical = attr.get("href") or ""
        elif name == "img":
            self.page.images.append((attr.get("src", ""), "alt" not in attr))
        elif name == "a" and attr.get("href"):
            self.page.links.append(attr["href"])

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"script", "style"}:
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        if name == "title":
            self._in_title = False
            self.page.title = clean_text("".join(self._title_parts))
        elif name == "h1" and self._in_h1:
            self._finish_h1()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)

    def close(self) -> None:
        super().close()
        if self._in_h1:
            self._finish_h1()
        if self._in_title and not self.page.title:
            self.page.title = clean_text("".join(self._title_parts))

    def _finish_h1(self) -> None:
        self._in_h1 = False
        text = clean_text("".join(self._h1_parts))
        if text:
            self.page.h1.append(text)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def directive_noindex(value: str) -> bool:
    tokens = re.split(r"[,;:\s]+", value.lower())
    return "noindex" in tokens or "none" in tokens


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return url.strip()
    port = parts.port
    if port and not (scheme == "https" and port == 443):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    path = re.sub(r"/+", "/", parts.path) or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def origin_root(url: str) -> str:
    parts = urlsplit(normalize_url(url))
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def same_origin(url: str, origin: str) -> bool:
    left = urlsplit(normalize_url(url))
    right = urlsplit(normalize_url(origin))
    return (left.scheme, left.hostname, left.port) == (right.scheme, right.hostname, right.port)


def local_or_private_host(hostname: str) -> bool:
    """True for localhost and for private, loopback, or link-local addresses."""

    host = hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified


def validate_site(site: str) -> str:
    parts = urlsplit(site.strip())
    if parts.username or parts.password:
        raise ValueError("site URL must not include credentials")
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("site must be an absolute HTTPS URL")
    if local_or_private_host(parts.hostname):
        raise ValueError("site must not target localhost or a private or loopback address")
    return normalize_url(site)


def decode_body(body: bytes, headers: dict[str, str]) -> str:
    charset = ""
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=\s*['\"]?([a-zA-Z0-9._-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    if not charset:
        head = body[:800].decode("ascii", errors="ignore")
        meta = re.search(r"charset=['\"]?\s*([a-zA-Z0-9._-]+)", head, re.I)
        if meta:
            charset = meta.group(1)
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def looks_html(headers: dict[str, str], body: bytes) -> bool:
    content_type = headers.get("content-type", "").lower()
    if "html" in content_type:
        return True
    if content_type:
        return False
    sample = body[:500].lstrip().lower()
    return sample.startswith(b"<!doctype html") or sample.startswith(b"<html") or b"<title" in sample


def parse_html(text: str) -> ParsedPage:
    parser = HTMLExtractor()
    parser.feed(text)
    parser.close()
    return parser.page


def parse_robots(text: str) -> RobotsFile:
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    saw_rule = False
    sitemaps: list[str] = []

    def flush() -> None:
        nonlocal agents, rules, saw_rule
        if agents:
            groups.append((agents, rules))
        agents = []
        rules = []
        saw_rule = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if saw_rule:
                flush()
            if value:
                agents.append(value.lower())
        elif key in {"allow", "disallow"}:
            if not agents:
                continue
            saw_rule = True
            rules.append((key == "allow", value))
        elif key == "sitemap" and value:
            sitemaps.append(value)
    flush()

    crawler_ua = USER_AGENT.lower()
    matched: list[tuple[int, list[tuple[bool, str]]]] = []
    star: list[tuple[bool, str]] = []
    for group_agents, group_rules in groups:
        lengths = [len(agent) for agent in group_agents if agent != "*" and crawler_ua.startswith(agent)]
        if lengths:
            matched.append((max(lengths), group_rules))
        elif "*" in group_agents:
            star.extend(group_rules)
    if matched:
        best = max(item[0] for item in matched)
        chosen: list[tuple[bool, str]] = []
        for length, group_rules in matched:
            if length == best:
                chosen.extend(group_rules)
    else:
        chosen = star

    unique_sitemaps: list[str] = []
    seen: set[str] = set()
    for sitemap in sitemaps:
        if sitemap not in seen:
            seen.add(sitemap)
            unique_sitemaps.append(sitemap)
    return RobotsFile(chosen, unique_sitemaps)


def robots_path(url: str) -> str:
    parts = urlsplit(normalize_url(url))
    path = parts.path or "/"
    if parts.query:
        return f"{path}?{parts.query}"
    return path


def rule_matches(rule: str, path: str) -> bool:
    if rule == "":
        return False
    pattern: list[str] = ["^"]
    for index, char in enumerate(rule):
        if char == "*":
            pattern.append(".*")
        elif char == "$" and index == len(rule) - 1:
            pattern.append("$")
        else:
            pattern.append(re.escape(char))
    if not rule.endswith("$"):
        pattern.append(".*")
    return re.match("".join(pattern), path) is not None


def robots_decision(url: str, rules: list[tuple[bool, str]]) -> tuple[bool, str | None]:
    """Return whether ``url`` may be fetched and the blocking rule, if any."""

    path = robots_path(url)
    matches: list[tuple[int, int, bool, str]] = []
    for allow, rule in rules:
        if rule == "":
            continue
        if rule_matches(rule, path):
            matches.append((len(rule), 1 if allow else 0, allow, rule))
    if not matches:
        return True, None
    best_length = max(item[0] for item in matches)
    best = [item for item in matches if item[0] == best_length]
    best.sort(key=lambda item: item[1])
    allow, rule = best[-1][2], best[-1][3]
    if allow:
        return True, None
    return False, f"Disallow: {rule}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(body: bytes) -> tuple[str, list[str], list[str], str | None]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        return "invalid", [], [], str(exc)
    kind = local_name(root.tag)
    locs: list[str] = []
    children: list[str] = []
    if kind == "urlset":
        for node in root:
            if local_name(node.tag) != "url":
                continue
            for child in node:
                if local_name(child.tag) == "loc" and child.text and child.text.strip():
                    locs.append(child.text.strip())
        return "urlset", locs, children, None
    if kind == "sitemapindex":
        for node in root:
            if local_name(node.tag) != "sitemap":
                continue
            for child in node:
                if local_name(child.tag) == "loc" and child.text and child.text.strip():
                    children.append(child.text.strip())
        return "sitemapindex", locs, children, None
    return "unknown", [], [], None


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only when the next URL stays on the same origin.

    urllib would otherwise open the Location target before the audit can
    reject it. Raising here stops that request.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not same_origin(newurl, req.full_url):
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                "cross-origin redirect blocked",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_fetch(url: str, timeout: float = 15.0) -> FetchResult:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    opener = urllib.request.build_opener(SameOriginRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return FetchResult(response.status, response.read(MAX_BYTES), headers, response.geturl())
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_BYTES) if exc.fp else b""
        headers = {key.lower(): value for key, value in (exc.headers.items() if exc.headers else [])}
        final = getattr(exc, "geturl", lambda: url)()
        return FetchResult(exc.code, body, headers, final or url)
    except Exception as exc:  # network and protocol failures stay in the report
        return FetchResult(0, b"", {}, url, error=f"{type(exc).__name__}: {exc}")


def finding(
    check: str,
    url: str,
    observation: str,
    severity: str,
    impact: str,
    fix: str,
    recheck: str,
    checked_at: str,
) -> dict[str, str]:
    return {
        "check": check,
        "url": url,
        "observation": observation,
        "source": "crawl",
        "severity": severity,
        "impact": impact,
        "fix": fix,
        "recheck": recheck,
        "checked_at": checked_at,
    }


def safe_fetch(fetch: Callable[[str], FetchResult], url: str) -> FetchResult:
    try:
        result = fetch(url)
    except Exception as exc:  # a caller-supplied fetch may fail per URL
        return FetchResult(0, b"", {}, url, error=f"{type(exc).__name__}: {exc}")
    if not isinstance(result, FetchResult):
        return FetchResult(0, b"", {}, url, error="fetch returned an unexpected value")
    if result.final_url is None:
        result.final_url = url
    return result


def audit_site(site: str, max_pages: int, fetch: Callable[[str], FetchResult]) -> dict[str, object]:
    """Crawl ``site`` and return the audit report. ``fetch`` is injectable for tests."""

    if max_pages < 1:
        raise ValueError("max-pages must be a positive integer")
    start = validate_site(site)
    origin = origin_root(start)
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    robots_url = f"{origin}/robots.txt"
    robots_result = safe_fetch(fetch, robots_url)
    robots_error = robots_result.error
    # 5xx or a dropped connection hides the rules, so the crawl stops instead of guessing.
    robots_unavailable = robots_result.status == 0 or robots_result.status >= 500
    parsed_robots = RobotsFile()
    if robots_result.status == 200:
        parsed_robots = parse_robots(decode_body(robots_result.body, robots_result.headers or {}).lstrip("\ufeff"))

    blocked: list[dict[str, str | None]] = []
    blocked_seen: set[str] = set()
    sitemap_documents: list[dict[str, object]] = []
    sitemap_entries: list[tuple[str, str]] = []
    sitemap_truncated = False
    off_origin_sitemap_urls: list[str] = []

    def remember_block(url: str, rule: str, referrer: str | None) -> None:
        if url in blocked_seen:
            return
        blocked_seen.add(url)
        blocked.append({"url": url, "rule": rule, "referrer": referrer})

    skipped_reason = None
    if robots_unavailable:
        skipped_reason = (
            f"robots.txt returned HTTP {robots_result.status}; pages were not fetched "
            "because the allow rules could not be read."
        )
        if robots_error:
            skipped_reason = f"{skipped_reason} {robots_error}"
    else:
        sitemap_seeds = list(parsed_robots.sitemaps)
        if not sitemap_seeds:
            sitemap_seeds = [f"{origin}/sitemap.xml"]
        pending_docs: deque[str] = deque()
        seen_docs: set[str] = set()
        for seed in sitemap_seeds:
            absolute = normalize_url(urljoin(robots_url, seed))
            if not same_origin(absolute, origin):
                sitemap_documents.append(
                    {"url": absolute, "status": None, "type": "skipped", "error": "off_origin"}
                )
                continue
            allowed, rule = robots_decision(absolute, parsed_robots.rules)
            if not allowed and rule:
                remember_block(absolute, rule, robots_url)
                sitemap_documents.append(
                    {"url": absolute, "status": None, "type": "skipped", "error": "robots"}
                )
                continue
            if absolute not in seen_docs:
                seen_docs.add(absolute)
                pending_docs.append(absolute)

        while pending_docs and len(sitemap_documents) < CHILD_SITEMAP_CAP:
            doc_url = pending_docs.popleft()
            doc = safe_fetch(fetch, doc_url)
            if doc.status != 200:
                sitemap_documents.append(
                    {
                        "url": doc_url,
                        "status": doc.status,
                        "type": "missing" if doc.status == 404 else "error",
                        "error": doc.error,
                    }
                )
                continue
            kind, locs, children, error = parse_sitemap(doc.body)
            sitemap_documents.append({"url": doc_url, "status": doc.status, "type": kind, "error": error})
            for loc in locs:
                if len(sitemap_entries) >= SITEMAP_URL_CAP:
                    sitemap_truncated = True
                    break
                absolute = normalize_url(urljoin(doc_url, loc))
                if not same_origin(absolute, origin):
                    if absolute not in off_origin_sitemap_urls:
                        off_origin_sitemap_urls.append(absolute)
                    continue
                sitemap_entries.append((absolute, doc_url))
            if kind == "sitemapindex":
                for child in children:
                    if len(seen_docs) >= CHILD_SITEMAP_CAP:
                        sitemap_truncated = True
                        break
                    absolute = normalize_url(urljoin(doc_url, child))
                    if not same_origin(absolute, origin):
                        sitemap_documents.append(
                            {"url": absolute, "status": None, "type": "skipped", "error": "off_origin"}
                        )
                        continue
                    allowed, rule = robots_decision(absolute, parsed_robots.rules)
                    if not allowed and rule:
                        remember_block(absolute, rule, doc_url)
                        continue
                    if absolute not in seen_docs:
                        seen_docs.add(absolute)
                        pending_docs.append(absolute)

    referrers: dict[str, list[dict[str, str | None]]] = {}
    queue: deque[str] = deque()
    queued: set[str] = set()
    queue_cap = max_pages * 25
    queue_truncated = False
    pending_sitemap = deque(sitemap_entries)

    def add_ref(url: str, via: str, source: str | None) -> None:
        item = {"via": via, "from": source}
        refs = referrers.setdefault(url, [])
        if item not in refs:
            refs.append(item)

    def enqueue(url: str, via: str, source: str | None) -> None:
        nonlocal queue_truncated
        normalized = normalize_url(url)
        parts = urlsplit(normalized)
        if parts.scheme != "https" or not parts.hostname:
            return
        if not same_origin(normalized, origin):
            return
        allowed, rule = robots_decision(normalized, parsed_robots.rules)
        if not allowed and rule:
            remember_block(normalized, rule, source)
            return
        add_ref(normalized, via, source)
        if normalized in queued:
            return
        if len(queued) >= queue_cap:
            queue_truncated = True
            return
        queued.add(normalized)
        queue.append(normalized)

    pages: list[dict[str, object]] = []
    if skipped_reason is None:
        enqueue(start, "seed", None)
        while len(pages) < max_pages:
            if not queue:
                while pending_sitemap:
                    candidate, doc_url = pending_sitemap.popleft()
                    if candidate in queued:
                        add_ref(candidate, "sitemap", doc_url)
                        continue
                    enqueue(candidate, "sitemap", doc_url)
                    if candidate in queued:
                        break
                if not queue:
                    break
            current = queue.popleft()
            result = safe_fetch(fetch, current)
            requested_url = current
            final_url = normalize_url(result.final_url or current)
            # A followed redirect returns the destination body. Keep that body off this URL.
            redirected = final_url != requested_url
            headers = result.headers or {}
            content_type = headers.get("content-type", "")
            html = looks_html(headers, result.body)
            stayed = same_origin(final_url, origin)
            parsed = ParsedPage()
            parse_error = None
            if html and result.status == 200 and stayed and not result.error and not redirected:
                try:
                    parsed = parse_html(decode_body(result.body, headers))
                except Exception as exc:  # malformed markup should not abort the crawl
                    parse_error = f"{type(exc).__name__}: {exc}"
            base = current
            if parsed.base_href:
                base = urljoin(current, parsed.base_href)
            canonical = None
            if parsed.canonical:
                canonical = normalize_url(urljoin(base, parsed.canonical))
            missing_alt: list[dict[str, str]] = []
            for src, alt_missing in parsed.images:
                if not alt_missing:
                    continue
                resolved = normalize_url(urljoin(base, src)) if src else ""
                missing_alt.append({"src": resolved or src})
            noindex = False
            if not redirected:
                noindex = directive_noindex(headers.get("x-robots-tag", "")) or parsed.noindex
            pages.append(
                {
                    "url": requested_url,
                    "requested_url": requested_url,
                    "final_url": final_url,
                    "status": result.status,
                    "content_type": content_type,
                    "title": parsed.title,
                    "description": parsed.description,
                    "h1": parsed.h1,
                    "canonical": canonical,
                    "noindex": noindex,
                    "missing_alt": missing_alt,
                    "error": result.error or parse_error,
                }
            )
            if redirected and stayed:
                enqueue(final_url, "redirect", requested_url)
            if parsed.links and result.status == 200 and stayed and not redirected:
                for href in parsed.links:
                    if href.lower().startswith(("mailto:", "tel:", "javascript:")):
                        continue
                    enqueue(urljoin(base, href), "link", current)

    findings: list[dict[str, str]] = []
    internal_404: list[dict[str, object]] = []
    for page in pages:
        url = str(page["url"])
        requested_url = str(page.get("requested_url") or url)
        final_url = normalize_url(str(page.get("final_url") or requested_url))
        redirected = final_url != normalize_url(requested_url)
        status = int(page["status"])
        content_type = str(page["content_type"])
        html = "html" in content_type.lower() or (not content_type and bool(page["title"] or page["h1"] or page["canonical"]))
        # Pages parsed from a body without a content type still have extracted fields.
        if page["title"] or page["h1"] or page["canonical"] or page["description"] or page["missing_alt"]:
            html = True
        if redirected:
            findings.append(finding(
                "redirect", requested_url,
                f"Requested URL redirects to {final_url}.",
                "medium",
                "The response body belongs to the final URL, so this address was not audited as its own page.",
                "Link directly to the final URL or serve the intended page at the requested URL.",
                "Fetch the requested URL and confirm the final URL matches it.",
                checked_at,
            ))
            continue
        if status == 200 and html:
            if not page["title"]:
                findings.append(finding(
                    "missing_title", url, "Title is missing.", "high",
                    "Search results and the browser tab have no page name to show.",
                    "Add one descriptive title element.",
                    "Fetch the URL and confirm a non-empty title.", checked_at,
                ))
            if not page["description"]:
                findings.append(finding(
                    "missing_description", url, "Meta description is missing.", "medium",
                    "Search engines may build the snippet from unrelated text on the page.",
                    "Add a meta description that summarizes the page.",
                    "Fetch the URL and confirm a non-empty meta description.", checked_at,
                ))
            h1 = page["h1"]
            if not h1:
                findings.append(finding(
                    "missing_h1", url, "H1 is missing.", "high",
                    "The page has no primary heading that states its topic.",
                    "Add one H1 that states the page topic.",
                    "Fetch the URL and confirm one non-empty H1.", checked_at,
                ))
            elif isinstance(h1, list) and len(h1) > 1:
                findings.append(finding(
                    "multiple_h1", url, f"Page has {len(h1)} H1 elements.", "low",
                    "More than one H1 makes the main topic of the page ambiguous.",
                    "Keep a single H1 and demote the others.",
                    "Fetch the URL and confirm one H1.", checked_at,
                ))
            canonical = page["canonical"]
            if not canonical:
                findings.append(finding(
                    "missing_canonical", url, "Canonical link is missing.", "medium",
                    "Duplicate URLs can split indexing signals without a preferred URL.",
                    "Add a canonical link to the preferred URL.",
                    "Fetch the URL and confirm one canonical.", checked_at,
                ))
            elif not same_origin(str(canonical), origin):
                findings.append(finding(
                    "canonical_cross_origin", url,
                    f"Canonical points outside the origin: {canonical}.", "high",
                    "The canonical tells search engines to index a different site instead of this one.",
                    "Point the canonical at the preferred same-origin URL.",
                    "Fetch the URL and confirm the canonical host.", checked_at,
                ))
            if page["noindex"]:
                findings.append(finding(
                    "noindex", url, "Page is marked noindex.", "high",
                    "Search engines are instructed to keep this URL out of the index.",
                    "Remove noindex if this URL should be indexed.",
                    "Fetch the URL and confirm robots no longer sends noindex.", checked_at,
                ))
            missing = page["missing_alt"]
            if isinstance(missing, list) and missing:
                findings.append(finding(
                    "missing_alt", url, f"{len(missing)} image(s) have no alt attribute.", "low",
                    "Images without an alt attribute are harder to understand for visitors who do not see them.",
                    "Add an alt attribute to each informative image.",
                    "Fetch the URL and confirm each img has an alt attribute.", checked_at,
                ))
        refs = referrers.get(url, [])
        internal_from = [ref["from"] for ref in refs if ref["via"] == "link" and ref["from"]]
        if status == 404 and internal_from:
            internal_404.append({"to": url, "status": 404, "from": internal_from})
            findings.append(finding(
                "internal_404", url,
                f"Internal link returns HTTP 404. Referrers: {', '.join(str(item) for item in internal_from)}.",
                "high",
                "People and crawlers that follow this internal link reach a missing page.",
                "Restore the URL or replace the internal link.",
                "Fetch the target and confirm it no longer returns 404.", checked_at,
            ))
        elif status >= 400 or status == 0:
            detail = f"HTTP {status}."
            if page["error"]:
                detail = f"{detail} {page['error']}"
            failed = status >= 500 or status == 0
            findings.append(finding(
                "http_status", url, detail,
                "high" if failed else "medium",
                "The server did not return the page, so its content could not be checked."
                if failed else
                "The URL returns an error, so visitors and crawlers may not get the page.",
                "Make the URL return a successful response or remove links to it.",
                "Fetch the URL and confirm the status.", checked_at,
            ))

    crawl_truncated = queue_truncated or bool(queue) or bool(pending_sitemap)
    not_checked = [dict(item) for item in NOT_CHECKED]
    if robots_unavailable:
        not_checked.append(
            {
                "check": "on_page",
                "label": "On-page crawl",
                "status": "not_checked",
                "reason": skipped_reason or "robots.txt could not be read, so pages were not fetched.",
            }
        )
    return {
        "agent": "technical_audit",
        "schema_version": 1,
        "status": "blocked" if robots_unavailable else "completed",
        "checked_at": checked_at,
        "inputs": {"site": start, "max_pages": max_pages},
        "origin": origin,
        "robots": {
            "url": robots_url,
            "status": robots_result.status,
            "error": robots_error,
            "sitemaps": list(parsed_robots.sitemaps),
            "skipped_reason": skipped_reason,
            "blocked": blocked,
        },
        "sitemap": {
            "documents": sitemap_documents,
            "urls": [url for url, _doc in sitemap_entries],
            "off_origin_urls": off_origin_sitemap_urls,
            "truncated": sitemap_truncated,
        },
        "crawl": {
            "status": "not_checked" if robots_unavailable else "completed",
            "max_pages": max_pages,
            "fetched_pages": len(pages),
            "truncated": crawl_truncated,
            "reason": skipped_reason if robots_unavailable else None,
            "skipped_reason": skipped_reason,
        },
        "pages": pages,
        "internal_404": internal_404,
        "findings": findings,
        "not_checked": not_checked,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="technical_audit",
        description=(
            "Bounded same-origin technical SEO audit. "
            "Does not call Search Console, PageSpeed Insights, or Yandex Webmaster."
        ),
    )
    parser.add_argument("--site", required=True, help="Absolute HTTPS URL to crawl")
    parser.add_argument("--max-pages", required=True, type=int, help="Maximum same-origin pages to fetch")
    parser.add_argument("--output", required=True, help="Path of the JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, fetch: Callable[[str], FetchResult] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit:
        raise
    try:
        if args.max_pages < 1:
            raise ValueError("max-pages must be a positive integer")
        validate_site(args.site)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = audit_site(args.site, args.max_pages, fetch or default_fetch)
    inputs = report["inputs"]
    if isinstance(inputs, dict):
        inputs["output"] = str(args.output)
    path = Path(args.output)
    try:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
