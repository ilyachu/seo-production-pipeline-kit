#!/usr/bin/env python3
"""Клиент Wordstat через Yandex Cloud Search API (только стандартная библиотека).

Бэкенд один — Yandex Cloud Search API. Аутентификация: короткоживущий JWT PS256,
подписанный через `openssl`, обмен на IAM-токен, затем вызов
POST https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests

Команды:
  doctor  — только структурная проверка конфига, без сети и без секретов в выводе
  top     — сбор топ-запросов и ассоциаций по фразе, вывод JSON или CSV

Коды возврата:
  0 — успех
  2 — конфиг неполный или невалидный (в т.ч. незаполненные плейсхолдеры)
  3 — конфиг или файл авторизованного ключа не найден / не читается
  4 — ошибка сети или API
  5 — ошибка аутентификации либо не выдана роль search-api.webSearch.user
"""

import argparse
import base64
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

EXIT_OK = 0
EXIT_CONFIG_INCOMPLETE = 2
EXIT_CONFIG_MISSING = 3
EXIT_NETWORK = 4
EXIT_AUTH = 5

DEFAULT_IAM_ENDPOINT = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
DEFAULT_TOP_REQUESTS_ENDPOINT = (
    "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests"
)
JWT_TTL_SECONDS = 360
PLACEHOLDER_MARKERS = ("REPLACE_ME", "<", "PUT_", "TODO")


class WordstatError(Exception):
    """Ошибка с готовым для пользователя текстом и кодом возврата."""

    def __init__(self, message, exit_code=EXIT_NETWORK):
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------- #
# Безопасность вывода
# --------------------------------------------------------------------------- #

_PEM_RE = re.compile(r"-----BEGIN[^-]*-----.*?-----END[^-]*-----", re.DOTALL)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)
_JWTISH_RE = re.compile(r"\b[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")


def scrub(text):
    """Убирает из строки всё, что похоже на секрет (PEM, Bearer-токен, JWT)."""
    text = _PEM_RE.sub("<PRIVATE KEY REDACTED>", str(text))
    text = _BEARER_RE.sub(r"\1<REDACTED>", text)
    text = _JWTISH_RE.sub("<TOKEN REDACTED>", text)
    return text


# --------------------------------------------------------------------------- #
# Конфиг
# --------------------------------------------------------------------------- #


def load_config(path):
    """Читает JSON-конфиг. Код 3 — нет файла; код 2 — JSON невалиден."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise WordstatError(
            "Конфиг не найден: %s\n"
            "Скопируй skills/seo-wordstat-collector/config.example.json в config.json "
            "и заполни folder_id и путь к авторизованному ключу." % path,
            EXIT_CONFIG_MISSING,
        )
    except json.JSONDecodeError as exc:
        raise WordstatError(
            "Конфиг %s не является корректным JSON: %s" % (path, exc.msg),
            EXIT_CONFIG_INCOMPLETE,
        )


def _is_placeholder(value):
    text = str(value).strip()
    if not text:
        return True
    upper = text.upper()
    return any(marker in upper for marker in PLACEHOLDER_MARKERS)


def validate_config(config):
    """Структурная проверка конфига. Возвращает список проблем (пустой = всё ок).

    Сеть не трогает, содержимое приватного ключа не читает и не печатает.
    """
    problems = []

    if not isinstance(config, dict):
        return ["Конфиг должен быть JSON-объектом."]

    backend = config.get("backend")
    if backend is None:
        problems.append('Не задан "backend". Поддерживается только "cloud".')
    elif backend != "cloud":
        problems.append(
            'Поле "backend" = %r, поддерживается только "cloud".' % (backend,)
        )

    folder_id = config.get("folder_id")
    if folder_id is None:
        problems.append('Не задан "folder_id" — ID каталога Yandex Cloud.')
    elif _is_placeholder(folder_id):
        problems.append(
            '"folder_id" содержит плейсхолдер — подставь реальный ID каталога.'
        )

    key_file = config.get("authorized_key_file")
    if key_file is None:
        problems.append(
            'Не задан "authorized_key_file" — путь к JSON авторизованного ключа '
            "сервисного аккаунта."
        )
    elif _is_placeholder(key_file):
        problems.append(
            '"authorized_key_file" содержит плейсхолдер — укажи путь к файлу ключа '
            "вне репозитория."
        )
    elif not os.path.exists(key_file):
        problems.append(
            'Файл авторизованного ключа не найден по пути из "authorized_key_file": %s'
            % key_file
        )

    endpoints = config.get("endpoints", {})
    if not isinstance(endpoints, dict):
        problems.append('Поле "endpoints" должно быть объектом.')
        endpoints = {}
    for name, default in (
        ("iam_token", DEFAULT_IAM_ENDPOINT),
        ("top_requests", DEFAULT_TOP_REQUESTS_ENDPOINT),
    ):
        url = endpoints.get(name, default)
        if not str(url).startswith("https://"):
            problems.append(
                'endpoints.%s должен быть HTTPS-адресом, сейчас: %s' % (name, url)
            )

    timeout = config.get("request_timeout_seconds", 30)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        problems.append(
            '"request_timeout_seconds" должен быть положительным числом.'
        )

    return problems


def endpoint(config, name, default):
    endpoints = config.get("endpoints") or {}
    if not isinstance(endpoints, dict):
        return default
    return endpoints.get(name) or default


def load_authorized_key(path):
    """Читает JSON авторизованного ключа и проверяет обязательные поля."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            key = json.load(handle)
    except FileNotFoundError:
        raise WordstatError(
            "Файл авторизованного ключа не найден: %s" % path, EXIT_CONFIG_MISSING
        )
    except json.JSONDecodeError:
        raise WordstatError(
            "Файл авторизованного ключа %s не является корректным JSON." % path,
            EXIT_CONFIG_MISSING,
        )

    key_id = key.get("id") or key.get("key_id")
    service_account_id = key.get("service_account_id")
    private_key = key.get("private_key")
    missing = []
    if not key_id:
        missing.append("id")
    if not service_account_id:
        missing.append("service_account_id")
    if not private_key:
        missing.append("private_key")
    if missing:
        raise WordstatError(
            "В файле авторизованного ключа нет обязательных полей: %s. "
            "Создай ключ заново: yc iam key create --service-account-name <sa> "
            "--output <файл вне репозитория>." % ", ".join(missing),
            EXIT_CONFIG_INCOMPLETE,
        )
    return {
        "key_id": key_id,
        "service_account_id": service_account_id,
        "private_key": private_key,
    }


# --------------------------------------------------------------------------- #
# JWT PS256 через openssl
# --------------------------------------------------------------------------- #


def b64url(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_ps256(signing_input, private_key_pem):
    """Подписывает данные RSA-PSS/SHA-256 через openssl.

    Приватный ключ пишется во временный файл с правами 0600 и передаётся только
    как путь: содержимое ключа не попадает ни в argv, ни в логи.
    """
    fd, key_path = tempfile.mkstemp(prefix="wordstat-key-", suffix=".pem")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(private_key_pem)
        try:
            proc = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-sigopt",
                    "rsa_padding_mode:pss",
                    "-sigopt",
                    "rsa_pss_saltlen:digest",
                    "-sign",
                    key_path,
                ],
                input=signing_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise WordstatError(
                "Не найден исполняемый файл openssl — он нужен для подписи JWT (PS256). "
                "Установи OpenSSL и повтори.",
                EXIT_AUTH,
            )
        if proc.returncode != 0:
            raise WordstatError(
                "openssl не смог подписать JWT (код %d). Проверь, что private_key "
                "в авторизованном ключе — валидный RSA PEM.\n%s"
                % (proc.returncode, scrub(proc.stderr.decode("utf-8", "replace")).strip()),
                EXIT_AUTH,
            )
        return proc.stdout
    finally:
        try:
            os.remove(key_path)
        except OSError:
            pass


def build_jwt(key, audience, now=None, ttl=JWT_TTL_SECONDS, signer=None):
    """Собирает короткоживущий JWT PS256 для обмена на IAM-токен."""
    signer = signer or sign_ps256
    issued_at = int(now if now is not None else time.time())
    header = {"typ": "JWT", "alg": "PS256", "kid": key["key_id"]}
    payload = {
        "aud": audience,
        "iss": key["service_account_id"],
        "iat": issued_at,
        "exp": issued_at + ttl,
    }
    signing_input = "%s.%s" % (
        b64url(json.dumps(header, separators=(",", ":"), sort_keys=True)),
        b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True)),
    )
    signature = signer(signing_input.encode("ascii"), key["private_key"])
    return "%s.%s" % (signing_input, b64url(signature))


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def http_post_json(url, payload, headers=None, timeout=30):
    """Единственный сетевой шов. В тестах подменяется целиком."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.getcode(), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return exc.code, raw
    except urllib.error.URLError as exc:
        raise WordstatError(
            "Сеть недоступна при обращении к %s: %s\n"
            "Проверь интернет-соединение, прокси и доступность домена "
            "*.api.cloud.yandex.net." % (url, scrub(exc.reason)),
            EXIT_NETWORK,
        )
    except TimeoutError:
        raise WordstatError(
            "Таймаут запроса к %s (%s c). Увеличь request_timeout_seconds в конфиге."
            % (url, timeout),
            EXIT_NETWORK,
        )


def _parse_json(raw, url):
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise WordstatError(
            "Ответ %s не является JSON. Первые 200 символов: %s"
            % (url, scrub(raw[:200])),
            EXIT_NETWORK,
        )


def _api_error(status, raw, url):
    """Переводит HTTP-код в понятную подсказку. Секретов в тексте нет."""
    excerpt = scrub(raw[:300]).strip()
    if status in (401, 403):
        return WordstatError(
            "Аутентификация или права отклонены (HTTP %d) на %s.\n"
            "Проверь по порядку:\n"
            "  1. сервисному аккаунту выдана роль search-api.webSearch.user "
            "на каталог или облако;\n"
            "  2. folder_id в конфиге — тот же каталог, где выдана роль;\n"
            "  3. авторизованный ключ не удалён и принадлежит этому сервисному аккаунту;\n"
            "  4. на часах машины корректное время (JWT живёт минуты).\n"
            "Ответ API: %s" % (status, url, excerpt),
            EXIT_AUTH,
        )
    if status == 404:
        return WordstatError(
            "Эндпоинт %s вернул 404. Проверь адрес в endpoints и что Search API "
            "включён в облаке.\nОтвет API: %s" % (url, excerpt),
            EXIT_NETWORK,
        )
    if status == 429:
        return WordstatError(
            "Превышен лимит запросов (HTTP 429) на %s. Сделай паузу и повтори, "
            "либо запроси увеличение квоты Search API.\nОтвет API: %s" % (url, excerpt),
            EXIT_NETWORK,
        )
    if status >= 500:
        return WordstatError(
            "Сервис вернул %d на %s — ошибка на стороне Yandex Cloud. Повтори позже.\n"
            "Ответ API: %s" % (status, url, excerpt),
            EXIT_NETWORK,
        )
    return WordstatError(
        "Запрос к %s завершился с HTTP %d.\nОтвет API: %s" % (url, status, excerpt),
        EXIT_NETWORK,
    )


def get_iam_token(config, key, http=None, signer=None, now=None):
    """Меняет JWT на IAM-токен. Возвращает строку токена (в логи не пишется).

    http и signer резолвятся в момент вызова, а не при импорте: подмена
    wordstat_client.http_post_json в тестах гарантированно отключает сеть.
    """
    http = http or http_post_json
    signer = signer or sign_ps256
    url = endpoint(config, "iam_token", DEFAULT_IAM_ENDPOINT)
    jwt = build_jwt(key, url, now=now, signer=signer)
    timeout = config.get("request_timeout_seconds", 30)
    status, raw = http(url, {"jwt": jwt}, None, timeout)
    if status != 200:
        raise _api_error(status, raw, url)
    data = _parse_json(raw, url)
    token = data.get("iamToken") or data.get("iam_token")
    if not token:
        raise WordstatError(
            "IAM-сервис ответил 200, но без поля iamToken. Проверь формат "
            "авторизованного ключа.",
            EXIT_AUTH,
        )
    return token


def fetch_top_requests(config, iam_token, phrase, regions=None, limit=None, http=None):
    """Вызывает /v2/wordstat/topRequests и возвращает сырой разобранный ответ."""
    http = http or http_post_json
    url = endpoint(config, "top_requests", DEFAULT_TOP_REQUESTS_ENDPOINT)
    payload = {"folderId": config.get("folder_id"), "phrase": phrase}
    if limit:
        payload["numPhrases"] = str(limit)
    if regions:
        payload["regions"] = [str(region) for region in regions]
    headers = {"Authorization": "Bearer %s" % iam_token}
    timeout = config.get("request_timeout_seconds", 30)
    status, raw = http(url, payload, headers, timeout)
    if status != 200:
        raise _api_error(status, raw, url)
    return _parse_json(raw, url)


# --------------------------------------------------------------------------- #
# Нормализация
# --------------------------------------------------------------------------- #

PHRASE_KEYS = ("phrase", "text", "query", "request", "keyword")
COUNT_KEYS = ("count", "number", "shows", "value", "frequency", "requestsCount")


def parse_count(raw):
    """Превращает «5 000», «5 000», 5000, «5000.0» в int. Иначе None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    text = str(raw).strip().replace(" ", "").replace(" ", "")
    text = text.replace(" ", "").replace("\t", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(float(text.replace(",", ".")))
    except ValueError:
        return None


def normalize_items(items):
    """Приводит список элементов API к {phrase, count_raw, count}.

    count_raw сохраняется как есть — исходная частотность не теряется даже если
    её не удалось разобрать в число.
    """
    normalized = []
    for item in items or []:
        if isinstance(item, str):
            normalized.append({"phrase": item, "count_raw": None, "count": None})
            continue
        if not isinstance(item, dict):
            continue
        phrase = None
        for key in PHRASE_KEYS:
            if item.get(key):
                phrase = str(item[key])
                break
        if not phrase:
            continue
        raw_count = None
        for key in COUNT_KEYS:
            if key in item and item[key] is not None:
                raw_count = item[key]
                break
        normalized.append(
            {
                "phrase": phrase,
                "count_raw": raw_count,
                "count": parse_count(raw_count),
            }
        )
    return normalized


def normalize_response(payload, limit=None):
    """Достаёт topRequests и associations из ответа API в любом из известных написаний."""
    if not isinstance(payload, dict):
        payload = {}
    for wrapper in ("result", "response"):
        if isinstance(payload.get(wrapper), dict):
            payload = payload[wrapper]
            break
    top = payload.get("topRequests")
    if top is None:
        top = payload.get("results")
    if top is None:
        top = payload.get("top_requests")
    if top is None:
        top = payload.get("requests", [])
    associations_present = any(key in payload for key in ("associations", "associationRequests", "association_requests"))
    associations = payload.get("associations")
    if associations is None:
        associations = payload.get("associationRequests")
    if associations is None:
        associations = payload.get("association_requests", [])

    result = {
        "topRequests": normalize_items(top),
        "associations": normalize_items(associations),
        "associationsFieldPresent": associations_present,
    }
    if limit:
        result["topRequests"] = result["topRequests"][:limit]
        result["associations"] = result["associations"][:limit]
    return result


def build_artifact(phrase, regions, limit, normalized):
    return {
        "source": "yandex-cloud-search-api/v2/wordstat/topRequests",
        "phrase": phrase,
        "regions": [str(region) for region in (regions or [])],
        "limit": limit,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "topRequests": normalized["topRequests"],
        "associations": normalized["associations"],
        "associations_field_present": normalized.get("associationsFieldPresent", "associations" in normalized),
    }


# --------------------------------------------------------------------------- #
# Вывод
# --------------------------------------------------------------------------- #

CSV_HEADER = ["section", "phrase", "count_raw", "count", "phrase_query", "regions"]


def format_csv(artifact):
    """CSV с CRLF и сохранённой сырой частотностью в колонке count_raw."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    regions = ";".join(artifact.get("regions") or [])
    for section in ("topRequests", "associations"):
        for row in artifact.get(section) or []:
            raw = row.get("count_raw")
            writer.writerow(
                [
                    section,
                    row.get("phrase", ""),
                    "" if raw is None else str(raw),
                    "" if row.get("count") is None else row["count"],
                    artifact.get("phrase", ""),
                    regions,
                ]
            )
    return buffer.getvalue()


def format_json(artifact):
    return json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"


def write_output(text, path, as_csv):
    if not path:
        sys.stdout.write(text)
        return
    # utf-8-sig для CSV: Excel корректно открывает кириллицу.
    encoding = "utf-8-sig" if as_csv else "utf-8"
    with open(path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #


def cmd_doctor(args):
    config = load_config(args.config)
    problems = validate_config(config)
    print("doctor: структурная проверка конфига %s (сеть не используется)" % args.config)
    if not problems:
        print("OK: конфиг заполнен структурно корректно.")
        print(
            "Дальше: python3 scripts/wordstat_client.py top "
            '--phrase "ваша фраза" --config %s' % args.config
        )
        return EXIT_OK
    print("Конфиг неполный — исправь %d пункт(ов):" % len(problems))
    for problem in problems:
        print("  - %s" % problem)
    print(
        "Секреты не читались и не выводились. Инструкция: "
        "skills/seo-wordstat-collector/references/setup.md"
    )
    return EXIT_CONFIG_INCOMPLETE


def cmd_top(args):
    config = load_config(args.config)
    problems = validate_config(config)
    if problems:
        raise WordstatError(
            "Конфиг не готов к запросу:\n  - %s" % "\n  - ".join(problems),
            EXIT_CONFIG_INCOMPLETE,
        )

    regions = args.region
    key = load_authorized_key(config["authorized_key_file"])
    iam_token = get_iam_token(config, key)
    payload = fetch_top_requests(config, iam_token, args.phrase, regions, args.limit)
    normalized = normalize_response(payload, limit=args.limit)
    artifact = build_artifact(args.phrase, regions, args.limit, normalized)

    as_csv = args.format == "csv"
    text = format_csv(artifact) if as_csv else format_json(artifact)
    write_output(text, args.output, as_csv)
    if args.output:
        print(
            "Готово: %d топ-запросов и %d ассоциаций → %s"
            % (len(artifact["topRequests"]), len(artifact["associations"]), args.output)
        )
    if not artifact["associations_field_present"]:
        print("Предупреждение: API-ответ не содержал поле associations; не дополняй его догадками.", file=sys.stderr)
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="wordstat_client.py",
        description="Сбор частотности Wordstat через Yandex Cloud Search API.",
    )
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser(
        "doctor", help="структурная проверка конфига без сети и без секретов"
    )
    doctor.add_argument("--config", required=True, help="путь к JSON-конфигу")

    top = subparsers.add_parser("top", help="топ-запросы и ассоциации по фразе")
    top.add_argument("--config", required=True, help="путь к JSON-конфигу")
    top.add_argument("--phrase", required=True, help="базовая фраза запроса")
    top.add_argument(
        "--region",
        action="append",
        required=True,
        help="ID региона Яндекса, можно повторять (225 — Россия, 213 — Москва)",
    )
    top.add_argument("--limit", type=int, default=50, help="сколько строк оставить в каждой секции")
    top.add_argument(
        "--format", choices=("json", "csv"), default="json", help="формат вывода"
    )
    top.add_argument("--output", help="файл для записи; без него — stdout")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_CONFIG_INCOMPLETE
    handlers = {"doctor": cmd_doctor, "top": cmd_top}
    try:
        return handlers[args.command](args)
    except WordstatError as exc:
        sys.stderr.write(scrub(str(exc)) + "\n")
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
