#!/usr/bin/env python3
"""Read-only owner data from Yandex Metrika, Yandex Webmaster, and Google Search Console.

Tokens are read only from the environment:
YANDEX_METRIKA_TOKEN, YANDEX_WEBMASTER_TOKEN, GSC_ACCESS_TOKEN.
They are sent as request headers and are never printed, stored, or accepted as arguments.

Usage:
    python3 tools/owner_data.py \\
        --site https://example.com/ \\
        --date1 2026-01-01 \\
        --date2 2026-01-31 \\
        --metrika-counter 12345678 \\
        --gsc-property sc-domain:example.com \\
        --output owner-data.json
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

USER_AGENT = "seo-owner-data/1.0"
MAX_BYTES = 1_000_000
SEARCH_ENGINE_LIMIT = 10
GOAL_LIMIT = 20
QUERY_LIMIT = 25
PROBLEM_LIMIT = 20
TIMEOUT_SECONDS = 20

METRIKA_TOKEN_ENV = "YANDEX_METRIKA_TOKEN"
WEBMASTER_TOKEN_ENV = "YANDEX_WEBMASTER_TOKEN"
GSC_TOKEN_ENV = "GSC_ACCESS_TOKEN"
METRIKA_ORIGIN = "https://api-metrika.yandex.net"
WEBMASTER_ORIGIN = "https://api.webmaster.yandex.net"
GSC_ORIGIN = "https://www.googleapis.com"
ALLOWED_HOSTS = {
    "api-metrika.yandex.net",
    "api.webmaster.yandex.net",
    "www.googleapis.com",
}
ORGANIC_FILTER = "ym:s:trafficSource=='organic'"
ORGANIC_METRICS = ("ym:s:visits", "ym:s:users")
EXIT_OUTPUT = 1
EXIT_USAGE = 2
EXIT_FAILED = 4

SECRET_RE = re.compile(
    r"(?i)\b(?:bearer|oauth)\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|ya29\.[A-Za-z0-9._~+/=-]+"
    r"|y0_[A-Za-z0-9._~+/=-]+"
    r"|access_token=[^\s&\"']+"
)


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = b""
    error: str | None = None


Transport = Callable[[HttpRequest], HttpResponse]


def redact(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = SECRET_RE.sub("[redacted]", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def read_token(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_or_private_host(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
    )


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not (scheme == "https" and port == 443):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    path = re.sub(r"/+", "/", parts.path) or "/"
    return f"{scheme}://{netloc}{path}"


def validate_site(site: str) -> str:
    parts = urlsplit(site.strip())
    if parts.username or parts.password:
        raise ValueError("site URL must not include credentials")
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("site must be an absolute HTTPS URL")
    if local_or_private_host(parts.hostname):
        raise ValueError("site must not target localhost or a private or loopback address")
    return normalize_url(site)


def parse_day(value: str, label: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{label} must be a real calendar date") from exc


def validate_gsc_property(value: str) -> str:
    property_id = value.strip()
    if not property_id or len(property_id) > 300 or any(char.isspace() for char in property_id):
        raise ValueError("gsc-property must be an exact Search Console property without spaces")
    domain = re.fullmatch(r"sc-domain:[A-Za-z0-9.-]+", property_id)
    parts = urlsplit(property_id)
    url_ok = (
        parts.scheme in {"http", "https"}
        and parts.hostname
        and not parts.username
        and not parts.password
        and parts.path in {"", "/"}
        and not parts.query
        and not parts.fragment
    )
    if domain or url_ok:
        return property_id
    raise ValueError("gsc-property must be sc-domain:host or an origin URL")


def validate_counter(value: str) -> str:
    counter = value.strip()
    if not re.fullmatch(r"[1-9][0-9]{0,19}", counter):
        raise ValueError("metrika-counter must be a positive decimal id")
    return counter


def as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def as_number(value: object) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return None


def hostname_of(value: str) -> str | None:
    text = value.strip().lower()
    if not text or any(char.isspace() for char in text):
        return None
    if "://" not in text:
        text = "https://" + text
    host = urlsplit(text).hostname
    return host.lower() if host else None


def default_transport(request: HttpRequest) -> HttpResponse:
    parts = urlsplit(request.url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        return HttpResponse(0, b"", "request host is not allowed")
    opener = urllib.request.build_opener(_NoRedirect())
    req = urllib.request.Request(
        request.url,
        data=request.body,
        headers=request.headers,
        method=request.method,
    )
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                return HttpResponse(response.status, b"", "response exceeded byte limit")
            return HttpResponse(response.status, raw, None)
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_BYTES + 1) if exc.fp is not None else b""
        if len(raw) > MAX_BYTES:
            raw = b""
        return HttpResponse(exc.code, raw, None)
    except Exception as exc:
        return HttpResponse(0, b"", f"{type(exc).__name__}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def error_detail(body: bytes, secrets: list[str]) -> str:
    if not body:
        return ""
    text = body.decode("utf-8", errors="replace")[:1000]
    message = ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            for key in ("message", "status", "error_description"):
                if isinstance(error.get(key), str):
                    message = error[key]
                    break
        elif isinstance(error, str):
            message = error
        if not message:
            for key in ("message", "error_description", "reason"):
                if isinstance(payload.get(key), str):
                    message = payload[key]
                    break
    elif payload is None:
        message = text[:180]
    message = redact(message, secrets)
    if message.lower() in {"error", "invalid", "unauthorized"}:
        return ""
    return message[:180]


def call_json(
    transport: Transport,
    request: HttpRequest,
    secrets: list[str],
) -> tuple[int, dict | None, str | None]:
    """Return HTTP status, a JSON object, and a sanitized failure reason."""

    try:
        response = transport(request)
    except Exception as exc:
        detail = redact(str(exc), secrets)[:180]
        return 0, None, detail or "network error"
    if response.error:
        detail = redact(response.error, secrets)
        return response.status, None, detail or "network error"
    if response.status == 0:
        return 0, None, "network error"
    try:
        payload = json.loads(response.body.decode("utf-8")) if response.body else None
    except (UnicodeError, json.JSONDecodeError):
        payload = None
    if response.status == 200 and isinstance(payload, dict):
        return 200, payload, None
    detail = error_detail(response.body, secrets)
    suffix = f": {detail}" if detail else ""
    if response.status in {401, 403, 404}:
        return response.status, None, f"HTTP {response.status}{suffix}"
    if response.status == 200:
        return response.status, None, "response was not a JSON object"
    return response.status, None, f"HTTP {response.status}{suffix}"


def auth_headers(token: str, scheme: str) -> dict[str, str]:
    return {
        "Authorization": f"{scheme} {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def get_json(
    transport: Transport,
    url: str,
    token: str,
    scheme: str,
    secrets: list[str],
) -> tuple[int, dict | None, str | None]:
    request = HttpRequest("GET", url, auth_headers(token, scheme), None)
    return call_json(transport, request, secrets)


def post_json(
    transport: Transport,
    url: str,
    token: str,
    scheme: str,
    payload: dict,
    secrets: list[str],
) -> tuple[int, dict | None, str | None]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = auth_headers(token, scheme)
    headers["Content-Type"] = "application/json"
    return call_json(transport, HttpRequest("POST", url, headers, body), secrets)


def period_of(date1: str, date2: str) -> dict[str, str]:
    return {"date1": date1, "date2": date2}


def source_row(
    source: str,
    property_id: str | None,
    date1: str,
    date2: str,
    checked_at: str,
    status: str,
    reason: str | None,
    counts: dict | None,
    data: dict | None,
) -> dict:
    return {
        "source": source,
        "property": property_id,
        "period": period_of(date1, date2),
        "checked_at": checked_at,
        "status": status,
        "reason": reason,
        "quota": None,
        "counts": counts,
        "data": data,
    }


def not_checked(
    source: str,
    property_id: str | None,
    date1: str,
    date2: str,
    checked_at: str,
    reason: str,
) -> dict:
    return source_row(source, property_id, date1, date2, checked_at, "not_checked", reason, None, None)


def failed(
    source: str,
    property_id: str | None,
    date1: str,
    date2: str,
    checked_at: str,
    reason: str,
) -> dict:
    return source_row(source, property_id, date1, date2, checked_at, "failed", reason, None, None)


def access_failure(status: int, detail: str) -> str | None:
    if status in {401, 403}:
        text = f"доступ не выдан ({detail})" if detail else "доступ не выдан"
        return text
    if status == 404:
        return detail or "HTTP 404"
    return None


def counter_hosts(payload: dict) -> set[str]:
    counter = payload.get("counter") if isinstance(payload.get("counter"), dict) else payload
    hosts: set[str] = set()
    values: list[object] = [counter.get("site"), counter.get("site2")]
    mirrors = counter.get("mirrors")
    if isinstance(mirrors, list):
        values.extend(mirrors)
    for value in values:
        if isinstance(value, str):
            host = hostname_of(value)
            if host:
                hosts.add(host)
        elif isinstance(value, dict):
            for key in ("site", "domain"):
                item = value.get(key)
                if isinstance(item, str):
                    host = hostname_of(item)
                    if host:
                        hosts.add(host)
    return hosts


def metrika_url(path: str, params: dict[str, str] | None = None) -> str:
    url = METRIKA_ORIGIN + path
    if params:
        return url + "?" + urlencode(params)
    return url


def collect_metrika(
    transport: Transport,
    token: str | None,
    counter_id: str | None,
    site_host: str,
    date1: str,
    date2: str,
    checked_at: str,
    secrets: list[str],
) -> dict:
    source = "yandex_metrika"
    if counter_id is None:
        return not_checked(
            source,
            None,
            date1,
            date2,
            checked_at,
            "Счётчик Метрики не задан (--metrika-counter отсутствует). Запрос к Метрике не отправлялся.",
        )
    if not token:
        return not_checked(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            f"Переменная {METRIKA_TOKEN_ENV} не задана. Запрос к Метрике не отправлялся.",
        )
    status, payload, detail = get_json(
        transport,
        metrika_url(f"/management/v1/counter/{counter_id}"),
        token,
        "OAuth",
        secrets,
    )
    denied = access_failure(status, detail or "")
    if denied:
        return not_checked(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            f"Метрика не подтвердила счётчик {counter_id}: {denied}. Приватный отчёт не запрашивался.",
        )
    if status != 200 or payload is None:
        return failed(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            f"Метрика не открыла счётчик {counter_id}: {detail or 'пустой ответ'}.",
        )
    counter = payload.get("counter") if isinstance(payload.get("counter"), dict) else payload
    returned_id = counter.get("id")
    if str(returned_id) != counter_id:
        return failed(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            f"Ответ Метрики не содержит счётчик {counter_id}.",
        )
    hosts = counter_hosts(payload)
    if site_host not in hosts:
        observed = ", ".join(sorted(hosts)) or "пусто"
        return not_checked(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            (
                f"Сайт счётчика ({observed}) не совпадает с {site_host}. "
                "Приватный отчёт не запрашивался."
            ),
        )
    organic_status, organic, organic_detail = get_json(
        transport,
        metrika_url(
            "/stat/v1/data",
            {
                "ids": counter_id,
                "metrics": ",".join(ORGANIC_METRICS),
                "dimensions": "ym:s:searchEngine",
                "filters": ORGANIC_FILTER,
                "date1": date1,
                "date2": date2,
                "limit": str(SEARCH_ENGINE_LIMIT),
                "accuracy": "full",
            },
        ),
        token,
        "OAuth",
        secrets,
    )
    if organic_status != 200 or organic is None:
        return failed(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            f"Органический отчёт Метрики не получен: {organic_detail or 'пустой ответ'}.",
        )
    totals = organic.get("totals")
    if not isinstance(totals, list) or len(totals) < 2:
        return failed(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            "Органический отчёт Метрики не содержит totals.",
        )
    visits = as_int(totals[0])
    users = as_int(totals[1])
    if visits is None or users is None or visits < 0 or users < 0:
        return failed(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            "Органические totals Метрики не являются неотрицательными целыми.",
        )
    rows = organic.get("data")
    if not isinstance(rows, list):
        return failed(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            "Органический отчёт Метрики не содержит data.",
        )
    engines: list[dict] = []
    for row in rows[:SEARCH_ENGINE_LIMIT]:
        if not isinstance(row, dict):
            return failed(source, counter_id, date1, date2, checked_at, "Строка Метрики повреждена.")
        dimensions = row.get("dimensions")
        metrics = row.get("metrics")
        if not isinstance(dimensions, list) or not dimensions or not isinstance(dimensions[0], dict):
            return failed(source, counter_id, date1, date2, checked_at, "Строка Метрики без поисковой системы.")
        name = dimensions[0].get("name") or dimensions[0].get("id")
        if not isinstance(name, str) or not name.strip():
            return failed(source, counter_id, date1, date2, checked_at, "Строка Метрики без имени источника.")
        if not isinstance(metrics, list) or len(metrics) < 2:
            return failed(source, counter_id, date1, date2, checked_at, "Строка Метрики без метрик.")
        row_visits = as_int(metrics[0])
        row_users = as_int(metrics[1])
        if row_visits is None or row_users is None or row_visits < 0 or row_users < 0:
            return failed(source, counter_id, date1, date2, checked_at, "Метрика строки не является целым числом.")
        engines.append({"name": name.strip()[:180], "visits": row_visits, "users": row_users})
    total_rows = organic.get("total_rows")
    parsed_total = as_int(total_rows) if total_rows is not None else None
    if total_rows is not None and (parsed_total is None or parsed_total < 0):
        return failed(source, counter_id, date1, date2, checked_at, "total_rows Метрики не является целым числом.")
    goals_status, goals_payload, goals_detail = get_json(
        transport,
        metrika_url(f"/management/v1/counter/{counter_id}/goals"),
        token,
        "OAuth",
        secrets,
    )
    if goals_status != 200 or goals_payload is None or not isinstance(goals_payload.get("goals"), list):
        return failed(
            source,
            counter_id,
            date1,
            date2,
            checked_at,
            f"Список целей Метрики не получен: {goals_detail or 'в ответе нет goals'}.",
        )
    goals_truncated = len(goals_payload["goals"]) > GOAL_LIMIT
    goals: list[dict] = []
    for item in goals_payload["goals"][:GOAL_LIMIT]:
        if not isinstance(item, dict):
            return failed(source, counter_id, date1, date2, checked_at, "Цель Метрики повреждена.")
        goal_id = as_int(item.get("id"))
        name = item.get("name")
        goal_type = item.get("type")
        if goal_id is None or goal_id < 1 or not isinstance(name, str) or not isinstance(goal_type, str):
            return failed(source, counter_id, date1, date2, checked_at, "Цель Метрики без id, имени или типа.")
        goals.append({"id": str(goal_id), "name": name.strip()[:180], "type": goal_type[:80], "reaches": None})
    if goals:
        metrics = [f"ym:s:goal{goal['id']}reaches" for goal in goals]
        reach_status, reach_payload, reach_detail = get_json(
            transport,
            metrika_url(
                "/stat/v1/data",
                {
                    "ids": counter_id,
                    "metrics": ",".join(metrics),
                    "filters": ORGANIC_FILTER,
                    "date1": date1,
                    "date2": date2,
                    "accuracy": "full",
                    "limit": "1",
                },
            ),
            token,
            "OAuth",
            secrets,
        )
        if reach_status != 200 or reach_payload is None or not isinstance(reach_payload.get("totals"), list):
            return failed(
                source,
                counter_id,
                date1,
                date2,
                checked_at,
                f"Достижения целей Метрики не получены: {reach_detail or 'нет totals'}.",
            )
        reach_totals = reach_payload["totals"]
        if len(reach_totals) < len(goals):
            return failed(
                source,
                counter_id,
                date1,
                date2,
                checked_at,
                "Отчёт целей Метрики короче списка целей.",
            )
        for goal, raw in zip(goals, reach_totals):
            reaches = as_int(raw)
            if reaches is None or reaches < 0:
                return failed(
                    source,
                    counter_id,
                    date1,
                    date2,
                    checked_at,
                    "Достижение цели Метрики не является целым числом.",
                )
            goal["reaches"] = reaches
    sampled = organic.get("sampled") if isinstance(organic.get("sampled"), bool) else None
    goal_reaches = sum(goal["reaches"] for goal in goals) if goals else 0
    data = {
        "counter_id": counter_id,
        "counter_site": site_host,
        "filter": ORGANIC_FILTER,
        "metrics": list(ORGANIC_METRICS),
        "sampled": sampled,
        "truncated": (
            (parsed_total is not None and parsed_total > len(engines))
            or len(rows) > len(engines)
            or goals_truncated
        ),
        "organic": {"visits": visits, "users": users, "search_engines": engines},
        "goals": goals,
        "limits": {"search_engines": SEARCH_ENGINE_LIMIT, "goals": GOAL_LIMIT},
    }
    counts = {
        "organic_visits": visits,
        "organic_users": users,
        "rows": len(engines),
        "total_rows": parsed_total,
        "goals": len(goals),
        "goal_reaches": goal_reaches,
    }
    return source_row(source, counter_id, date1, date2, checked_at, "ready", None, counts, data)


def webmaster_host_match(host: dict, site_host: str) -> bool:
    for key in ("ascii_host_url", "unicode_host_url"):
        value = host.get(key)
        if not isinstance(value, str):
            continue
        parts = urlsplit(value.strip())
        if (
            parts.scheme.lower() == "https"
            and (parts.hostname or "").lower() == site_host
            and not parts.username
        ):
            return True
    return False


def collect_webmaster(
    transport: Transport,
    token: str | None,
    site_host: str,
    date1: str,
    date2: str,
    checked_at: str,
    secrets: list[str],
) -> dict:
    source = "yandex_webmaster"
    property_id = f"https://{site_host}/"
    if not token:
        return not_checked(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Переменная {WEBMASTER_TOKEN_ENV} не задана. Запрос к Вебмастеру не отправлялся.",
        )
    status, payload, detail = get_json(
        transport,
        f"{WEBMASTER_ORIGIN}/v4/user",
        token,
        "OAuth",
        secrets,
    )
    denied = access_failure(status, detail or "")
    if denied:
        return not_checked(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Вебмастер не подтвердил доступ: {denied}. Диагностика не запрашивалась.",
        )
    if status != 200 or payload is None:
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Пользователь Вебмастера не получен: {detail or 'пустой ответ'}.",
        )
    user_id = payload.get("user_id")
    user_text = str(user_id) if isinstance(user_id, int) and not isinstance(user_id, bool) else ""
    if not re.fullmatch(r"[1-9][0-9]{0,19}", user_text):
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            "Ответ Вебмастера не содержит user_id. Хосты не запрашивались.",
        )
    hosts_status, hosts_payload, hosts_detail = get_json(
        transport,
        f"{WEBMASTER_ORIGIN}/v4/user/{user_text}/hosts",
        token,
        "OAuth",
        secrets,
    )
    if hosts_status in {401, 403, 404}:
        return not_checked(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Вебмастер не подтвердил хосты: {access_failure(hosts_status, hosts_detail or '')}.",
        )
    if hosts_status != 200 or hosts_payload is None or not isinstance(hosts_payload.get("hosts"), list):
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Список хостов Вебмастера не получен: {hosts_detail or 'в ответе нет hosts'}.",
        )
    matched = None
    for host in hosts_payload["hosts"]:
        if isinstance(host, dict) and webmaster_host_match(host, site_host):
            matched = host
            if host.get("verified") is True:
                break
    if matched is None:
        return not_checked(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            (
                f"Хост {site_host} отсутствует в аккаунте Вебмастера. "
                "Диагностика и сводка не запрашивались."
            ),
        )
    host_id = matched.get("host_id")
    if not isinstance(host_id, str) or not host_id.strip() or any(char.isspace() for char in host_id):
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            "Совпавший хост Вебмастера не содержит host_id.",
        )
    host_id = host_id.strip()
    encoded = quote(host_id, safe="")
    base = f"{WEBMASTER_ORIGIN}/v4/user/{user_text}/hosts/{encoded}"
    summary_status, summary, summary_detail = get_json(transport, base + "/summary", token, "OAuth", secrets)
    if summary_status != 200 or summary is None:
        return failed(
            source,
            host_id,
            date1,
            date2,
            checked_at,
            f"Сводка Вебмастера не получена: {summary_detail or 'пустой ответ'}.",
        )
    diag_status, diagnostics, diag_detail = get_json(
        transport,
        base + "/diagnostics",
        token,
        "OAuth",
        secrets,
    )
    if diag_status != 200 or diagnostics is None or not isinstance(diagnostics.get("problems"), dict):
        return failed(
            source,
            host_id,
            date1,
            date2,
            checked_at,
            f"Диагностика Вебмастера не получена: {diag_detail or 'в ответе нет problems'}.",
        )
    summary_fields = {}
    present = 0
    for key in ("sqi", "searchable_pages_count", "excluded_pages_count"):
        if key not in summary:
            summary_fields[key] = None
            continue
        number = as_int(summary.get(key))
        if number is None or number < 0:
            return failed(
                source,
                host_id,
                date1,
                date2,
                checked_at,
                f"Поле сводки {key} не является неотрицательным целым.",
            )
        summary_fields[key] = number
        present += 1
    problems_raw = diagnostics["problems"]
    problems: list[dict] = []
    for code in sorted(problems_raw)[:PROBLEM_LIMIT]:
        item = problems_raw[code]
        if not isinstance(code, str) or not isinstance(item, dict):
            return failed(source, host_id, date1, date2, checked_at, "Проблема Вебмастера повреждена.")
        severity = item.get("severity")
        state = item.get("state")
        if not isinstance(severity, str) or not isinstance(state, str):
            return failed(source, host_id, date1, date2, checked_at, "Проблема Вебмастера без severity или state.")
        problems.append({"code": code[:80], "severity": severity[:40], "state": state[:40]})
    verified = matched.get("verified") if isinstance(matched.get("verified"), bool) else None
    data = {
        "user_id": user_text,
        "host_id": host_id,
        "verified": verified,
        "summary_scope": "current",
        "summary": summary_fields,
        "problems": problems,
        "truncated": len(problems_raw) > len(problems),
        "limits": {"problems": PROBLEM_LIMIT},
    }
    counts = {
        "problems": len(problems),
        "problems_total": len(problems_raw),
        "summary_fields": present,
    }
    return source_row(source, host_id, date1, date2, checked_at, "ready", None, counts, data)


def gsc_query(
    transport: Transport,
    token: str,
    property_id: str,
    body: dict,
    secrets: list[str],
) -> tuple[int, dict | None, str | None]:
    encoded = quote(property_id, safe="")
    url = f"{GSC_ORIGIN}/webmasters/v3/sites/{encoded}/searchAnalytics/query"
    return post_json(transport, url, token, "Bearer", body, secrets)


def gsc_metrics(row: dict) -> tuple[int, int, int | float, int | float] | None:
    clicks = as_int(row.get("clicks"))
    impressions = as_int(row.get("impressions"))
    ctr = as_number(row.get("ctr"))
    position = as_number(row.get("position"))
    if clicks is None or impressions is None or ctr is None or position is None:
        return None
    if clicks < 0 or impressions < 0 or ctr < 0 or position < 0:
        return None
    return clicks, impressions, ctr, position


def collect_gsc(
    transport: Transport,
    token: str | None,
    property_id: str | None,
    date1: str,
    date2: str,
    checked_at: str,
    secrets: list[str],
) -> dict:
    source = "gsc"
    if property_id is None:
        return not_checked(
            source,
            None,
            date1,
            date2,
            checked_at,
            "Свойство Search Console не задано (--gsc-property отсутствует). Запрос к Search Console не отправлялся.",
        )
    if not token:
        return not_checked(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Переменная {GSC_TOKEN_ENV} не задана. Запрос к Search Console не отправлялся.",
        )
    status, payload, detail = get_json(
        transport,
        f"{GSC_ORIGIN}/webmasters/v3/sites",
        token,
        "Bearer",
        secrets,
    )
    denied = access_failure(status, detail or "")
    if denied:
        return not_checked(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Search Console не подтвердил доступ: {denied}. searchAnalytics не запрашивался.",
        )
    if status != 200 or payload is None:
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"Список свойств Search Console не получен: {detail or 'пустой ответ'}.",
        )
    if "error" in payload and "siteEntry" not in payload:
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            "Список свойств Search Console вернул ошибку вместо siteEntry.",
        )
    entries = payload.get("siteEntry", [])
    if not isinstance(entries, list):
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            "Поле siteEntry Search Console не является списком.",
        )
    found = False
    permission = None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("siteUrl") == property_id:
            found = True
            permission = entry.get("permissionLevel")
            break
    if not found:
        return not_checked(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            (
                f"Свойство {property_id} отсутствует в аккаунте Search Console. "
                "searchAnalytics не запрашивался."
            ),
        )
    if not isinstance(permission, str) or not permission:
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            "У свойства Search Console нет permissionLevel.",
        )
    window = {"startDate": date1, "endDate": date2, "searchType": "web"}
    totals_status, totals_payload, totals_detail = gsc_query(
        transport,
        token,
        property_id,
        window,
        secrets,
    )
    if totals_status != 200 or totals_payload is None:
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"searchAnalytics без разрезов не получен: {totals_detail or 'пустой ответ'}.",
        )
    total_rows = totals_payload.get("rows", [])
    empty_totals = total_rows == [] or "rows" not in totals_payload
    if total_rows is None:
        empty_totals = True
        total_rows = []
    if not isinstance(total_rows, list):
        return failed(source, property_id, date1, date2, checked_at, "searchAnalytics rows не является списком.")
    if empty_totals:
        clicks = 0
        impressions = 0
        ctr = 0
        position = 0
    else:
        if not isinstance(total_rows[0], dict):
            return failed(source, property_id, date1, date2, checked_at, "Строка searchAnalytics повреждена.")
        parsed = gsc_metrics(total_rows[0])
        if parsed is None:
            return failed(
                source,
                property_id,
                date1,
                date2,
                checked_at,
                "Итог searchAnalytics не содержит числовых clicks, impressions, ctr и position.",
            )
        clicks, impressions, ctr, position = parsed
    query_status, query_payload, query_detail = gsc_query(
        transport,
        token,
        property_id,
        {**window, "dimensions": ["query"], "rowLimit": QUERY_LIMIT},
        secrets,
    )
    if query_status != 200 or query_payload is None:
        return failed(
            source,
            property_id,
            date1,
            date2,
            checked_at,
            f"searchAnalytics по запросам не получен: {query_detail or 'пустой ответ'}.",
        )
    raw_rows = query_payload.get("rows", [])
    if raw_rows is None:
        raw_rows = []
    if not isinstance(raw_rows, list):
        return failed(source, property_id, date1, date2, checked_at, "Строки запросов Search Console повреждены.")
    queries: list[dict] = []
    for row in raw_rows[:QUERY_LIMIT]:
        if not isinstance(row, dict):
            return failed(source, property_id, date1, date2, checked_at, "Строка запроса Search Console повреждена.")
        keys = row.get("keys")
        if not isinstance(keys, list) or not keys or not isinstance(keys[0], str) or not keys[0].strip():
            return failed(source, property_id, date1, date2, checked_at, "Строка запроса без текста.")
        parsed = gsc_metrics(row)
        if parsed is None:
            return failed(source, property_id, date1, date2, checked_at, "Метрики строки запроса не числовые.")
        row_clicks, row_impressions, row_ctr, row_position = parsed
        queries.append(
            {
                "query": keys[0].strip()[:180],
                "clicks": row_clicks,
                "impressions": row_impressions,
                "ctr": row_ctr,
                "position": row_position,
            }
        )
    data = {
        "property": property_id,
        "permission_level": permission,
        "search_type": "web",
        "empty": empty_totals and not queries,
        "totals": {"clicks": clicks, "impressions": impressions, "ctr": ctr, "position": position},
        "queries": queries,
        "truncated": len(raw_rows) > len(queries),
        "limits": {"queries": QUERY_LIMIT},
    }
    counts = {"rows": len(queries), "clicks": clicks, "impressions": impressions}
    return source_row(source, property_id, date1, date2, checked_at, "ready", None, counts, data)


def overall_status(sources: list[dict]) -> str:
    statuses = {item["status"] for item in sources}
    if "failed" in statuses:
        return "failed"
    if statuses == {"ready"}:
        return "ready"
    return "needs_input"


def collect_report(
    site: str,
    date1: str,
    date2: str,
    counter_id: str | None,
    gsc_property: str | None,
    output: str,
    env: Mapping[str, str],
    transport: Transport,
    checked_at: str,
) -> dict:
    site_host = urlsplit(site).hostname or ""
    tokens = [
        read_token(env, METRIKA_TOKEN_ENV),
        read_token(env, WEBMASTER_TOKEN_ENV),
        read_token(env, GSC_TOKEN_ENV),
    ]
    secrets = [token for token in tokens if token]
    sources = [
        collect_metrika(transport, tokens[0], counter_id, site_host, date1, date2, checked_at, secrets),
        collect_webmaster(transport, tokens[1], site_host, date1, date2, checked_at, secrets),
        collect_gsc(transport, tokens[2], gsc_property, date1, date2, checked_at, secrets),
    ]
    return {
        "agent": "owner_data",
        "schema_version": 1,
        "status": overall_status(sources),
        "checked_at": checked_at,
        "inputs": {
            "site": site,
            "date1": date1,
            "date2": date2,
            "metrika_counter": counter_id,
            "gsc_property": gsc_property,
            "output": output,
        },
        "sources": sources,
    }


def dump_report(report: dict, secrets: list[str]) -> str:
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, "[redacted]")
    return SECRET_RE.sub("[redacted]", text)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="owner_data",
        description=(
            "Read-only Metrika, Webmaster, and Search Console snapshot. "
            "Reads tokens from the environment, never from arguments."
        ),
    )
    parser.add_argument("--site", required=True, help="Absolute HTTPS site URL")
    parser.add_argument("--date1", required=True, help="Period start YYYY-MM-DD")
    parser.add_argument("--date2", required=True, help="Period end YYYY-MM-DD")
    parser.add_argument(
        "--metrika-counter",
        help="Yandex Metrika counter id; omit to leave Metrika not_checked",
    )
    parser.add_argument(
        "--gsc-property",
        help="Exact Google Search Console property; omit to leave GSC not_checked",
    )
    parser.add_argument("--output", required=True, help="Path of the JSON report")
    return parser.parse_args(argv)


def reject_token_args(argv: list[str]) -> bool:
    for item in argv:
        name = item.split("=", 1)[0].lower()
        if name.startswith("--") and "token" in name:
            return True
    return False


def main(
    argv: list[str] | None = None,
    transport: Transport | None = None,
    now: Callable[[], str] | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    raw_args = sys.argv[1:] if argv is None else argv
    if reject_token_args(raw_args):
        print("error: tokens must be provided through the environment, not arguments", file=sys.stderr)
        return EXIT_USAGE
    try:
        args = parse_args(argv)
    except SystemExit:
        raise
    try:
        site = validate_site(args.site)
        start = parse_day(args.date1, "date1")
        end = parse_day(args.date2, "date2")
        if end < start:
            raise ValueError("date2 must not be earlier than date1")
        counter_id = validate_counter(args.metrika_counter) if args.metrika_counter is not None else None
        gsc_property = validate_gsc_property(args.gsc_property) if args.gsc_property is not None else None
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    selected_env = os.environ if env is None else env
    secrets = [
        token
        for token in (
            read_token(selected_env, METRIKA_TOKEN_ENV),
            read_token(selected_env, WEBMASTER_TOKEN_ENV),
            read_token(selected_env, GSC_TOKEN_ENV),
        )
        if token
    ]
    report = collect_report(
        site,
        args.date1,
        args.date2,
        counter_id,
        gsc_property,
        str(args.output),
        selected_env,
        transport or default_transport,
        (now or utc_now)(),
    )
    text = dump_report(report, secrets)
    path = Path(args.output)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"error: {redact(str(exc), secrets)}", file=sys.stderr)
        return EXIT_OUTPUT
    if report["status"] == "failed":
        reasons = [item["reason"] for item in report["sources"] if item["status"] == "failed" and item["reason"]]
        print("error: " + redact("; ".join(reasons), secrets), file=sys.stderr)
        return EXIT_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main())
