"""Оффлайн-тесты клиента Wordstat.

Сеть и подпись замоканы: реальных HTTP-запросов и реальных ключей здесь нет.
Запуск: python3 -m unittest tests/test_wordstat_client.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
)

import wordstat_client as wc  # noqa: E402

FAKE_PRIVATE_KEY = (
    "-----BEGIN PRIVATE KEY-----\n"
    "TOTALLY-FAKE-KEY-MATERIAL-FOR-TESTS-ONLY\n"
    "-----END PRIVATE KEY-----\n"
)
FAKE_IAM_TOKEN = "t1.fake-iam-token-value.abcdefghijklmnopqrstuvwxyz0123456789"


def write_temp(content, suffix=".json"):
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=suffix, delete=False, encoding="utf-8"
    )
    handle.write(content)
    handle.close()
    return handle.name


class ConfigValidationTest(unittest.TestCase):
    def setUp(self):
        self.key_path = write_temp(
            json.dumps(
                {
                    "id": "fake-key-id",
                    "service_account_id": "fake-sa-id",
                    "private_key": FAKE_PRIVATE_KEY,
                }
            )
        )
        self.addCleanup(os.remove, self.key_path)

    def valid_config(self, **overrides):
        config = {
            "backend": "cloud",
            "folder_id": "b1gfakefolderid",
            "authorized_key_file": self.key_path,
            "endpoints": {
                "iam_token": wc.DEFAULT_IAM_ENDPOINT,
                "top_requests": wc.DEFAULT_TOP_REQUESTS_ENDPOINT,
            },
            "default_region_ids": [225],
            "request_timeout_seconds": 30,
        }
        config.update(overrides)
        return config

    def test_valid_config_has_no_problems(self):
        self.assertEqual(wc.validate_config(self.valid_config()), [])

    def test_placeholder_folder_id_is_rejected(self):
        problems = wc.validate_config(self.valid_config(folder_id="REPLACE_ME_folder"))
        self.assertTrue(any("folder_id" in p for p in problems))

    def test_missing_folder_id_is_rejected(self):
        config = self.valid_config()
        del config["folder_id"]
        problems = wc.validate_config(config)
        self.assertTrue(any("folder_id" in p for p in problems))

    def test_non_cloud_backend_is_rejected(self):
        problems = wc.validate_config(self.valid_config(backend="wordstat-web"))
        self.assertTrue(any("backend" in p for p in problems))

    def test_non_https_endpoint_is_rejected(self):
        config = self.valid_config()
        config["endpoints"]["top_requests"] = "http://searchapi.api.cloud.yandex.net/x"
        problems = wc.validate_config(config)
        self.assertTrue(any("HTTPS" in p for p in problems))

    def test_missing_key_file_is_reported(self):
        config = self.valid_config(authorized_key_file="/nope/does-not-exist.json")
        problems = wc.validate_config(config)
        self.assertTrue(any("не найден" in p for p in problems))

    def test_example_config_is_incomplete_but_structurally_parseable(self):
        example = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "skills",
            "seo-wordstat-collector",
            "config.example.json",
        )
        config = wc.load_config(example)
        self.assertEqual(config["backend"], "cloud")
        problems = wc.validate_config(config)
        self.assertTrue(problems, "пример конфига обязан быть неполным")

    def test_doctor_on_example_config_returns_documented_exit_code(self):
        example = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "skills",
            "seo-wordstat-collector",
            "config.example.json",
        )
        code = wc.main(["doctor", "--config", example])
        self.assertEqual(code, wc.EXIT_CONFIG_INCOMPLETE)

    def test_missing_config_file_exits_with_config_missing(self):
        code = wc.main(["doctor", "--config", "/nope/missing-config.json"])
        self.assertEqual(code, wc.EXIT_CONFIG_MISSING)

    def test_malformed_config_exits_with_incomplete_code(self):
        path = write_temp("{not json")
        self.addCleanup(os.remove, path)
        code = wc.main(["doctor", "--config", path])
        self.assertEqual(code, wc.EXIT_CONFIG_INCOMPLETE)

    def test_top_requires_explicit_region(self):
        with self.assertRaises(SystemExit) as raised:
            wc.main(["top", "--config", "x.json", "--phrase", "x"])
        self.assertEqual(raised.exception.code, 2)


class NormalizationTest(unittest.TestCase):
    def test_normalizes_top_requests_and_associations(self):
        payload = {
            "topRequests": [
                {"phrase": "доставка цветов", "count": "5 000"},
                {"phrase": "доставка роз", "count": 1200},
            ],
            "associations": [{"phrase": "букет на 8 марта", "count": "310"}],
        }
        result = wc.normalize_response(payload)
        self.assertEqual(len(result["topRequests"]), 2)
        self.assertEqual(result["topRequests"][0]["phrase"], "доставка цветов")
        self.assertEqual(result["topRequests"][0]["count"], 5000)
        self.assertEqual(len(result["associations"]), 1)
        self.assertEqual(result["associations"][0]["count"], 310)

    def test_raw_frequency_is_preserved_verbatim(self):
        payload = {"topRequests": [{"phrase": "ключ", "count": "5 000"}]}
        row = wc.normalize_response(payload)["topRequests"][0]
        self.assertEqual(row["count_raw"], "5 000")
        self.assertEqual(row["count"], 5000)

    def test_unparsable_frequency_keeps_raw_and_null_count(self):
        payload = {"topRequests": [{"phrase": "ключ", "count": "<10"}]}
        row = wc.normalize_response(payload)["topRequests"][0]
        self.assertEqual(row["count_raw"], "<10")
        self.assertIsNone(row["count"])

    def test_alternative_key_spellings_are_accepted(self):
        payload = {
            "top_requests": [{"text": "фраза", "shows": "42"}],
            "association_requests": [{"query": "ассоциация", "number": "7"}],
        }
        result = wc.normalize_response(payload)
        self.assertEqual(result["topRequests"][0]["phrase"], "фраза")
        self.assertEqual(result["topRequests"][0]["count"], 42)
        self.assertEqual(result["associations"][0]["phrase"], "ассоциация")

    def test_cloud_results_key_is_accepted(self):
        payload = {
            "results": [{"phrase": "облачный ответ", "count": "19"}],
            "associations": [],
        }
        result = wc.normalize_response(payload)
        self.assertEqual(result["topRequests"][0]["phrase"], "облачный ответ")
        self.assertEqual(result["topRequests"][0]["count"], 19)

    def test_nested_cloud_result_wrapper_is_accepted(self):
        payload = {"result": {"results": [{"phrase": "wrapped", "count": "8"}], "associations": []}}
        result = wc.normalize_response(payload)
        self.assertEqual(result["topRequests"][0]["phrase"], "wrapped")
        self.assertTrue(result["associationsFieldPresent"])

    def test_missing_associations_field_is_visible(self):
        result = wc.normalize_response({"results": []})
        self.assertFalse(result["associationsFieldPresent"])

    def test_empty_and_malformed_payloads_do_not_crash(self):
        self.assertEqual(
            wc.normalize_response({}), {"topRequests": [], "associations": [], "associationsFieldPresent": False}
        )
        self.assertEqual(
            wc.normalize_response(None), {"topRequests": [], "associations": [], "associationsFieldPresent": False}
        )
        result = wc.normalize_response({"topRequests": [None, 5, {"count": 1}]})
        self.assertEqual(result["topRequests"], [])

    def test_limit_truncates_both_sections(self):
        payload = {
            "topRequests": [{"phrase": "p%d" % i, "count": i} for i in range(10)],
            "associations": [{"phrase": "a%d" % i, "count": i} for i in range(10)],
        }
        result = wc.normalize_response(payload, limit=3)
        self.assertEqual(len(result["topRequests"]), 3)
        self.assertEqual(len(result["associations"]), 3)

    def test_parse_count_handles_separators(self):
        self.assertEqual(wc.parse_count("5 000"), 5000)
        self.assertEqual(wc.parse_count("5 000"), 5000)
        self.assertEqual(wc.parse_count("1234"), 1234)
        self.assertEqual(wc.parse_count(1234), 1234)
        self.assertIsNone(wc.parse_count(""))
        self.assertIsNone(wc.parse_count(None))
        self.assertIsNone(wc.parse_count("н/д"))


class CsvEncodingTest(unittest.TestCase):
    def artifact(self, rows, associations=None):
        return wc.build_artifact(
            "доставка цветов",
            [225],
            10,
            {"topRequests": rows, "associations": associations or []},
        )

    def test_header_and_sections(self):
        artifact = self.artifact(
            [{"phrase": "ключ", "count_raw": "10", "count": 10}],
            [{"phrase": "ассоц", "count_raw": "3", "count": 3}],
        )
        csv_text = wc.format_csv(artifact)
        lines = csv_text.strip().split("\r\n")
        self.assertEqual(lines[0], ",".join(wc.CSV_HEADER))
        self.assertTrue(lines[1].startswith("topRequests,"))
        self.assertTrue(lines[2].startswith("associations,"))

    def test_commas_and_quotes_are_escaped(self):
        artifact = self.artifact(
            [{"phrase": 'цветы, "розы"', "count_raw": "10", "count": 10}]
        )
        csv_text = wc.format_csv(artifact)
        self.assertIn('"цветы, ""розы"""', csv_text)

    def test_raw_frequency_column_keeps_original_formatting(self):
        artifact = self.artifact(
            [{"phrase": "ключ", "count_raw": "5 000", "count": 5000}]
        )
        csv_text = wc.format_csv(artifact)
        self.assertIn("5 000", csv_text)

    def test_null_counts_become_empty_cells(self):
        artifact = self.artifact([{"phrase": "ключ", "count_raw": None, "count": None}])
        row = wc.format_csv(artifact).strip().split("\r\n")[1]
        self.assertEqual(row.split(",")[2], "")
        self.assertEqual(row.split(",")[3], "")

    def test_csv_file_is_written_as_utf8_sig(self):
        artifact = self.artifact([{"phrase": "цветы", "count_raw": "1", "count": 1}])
        path = write_temp("", suffix=".csv")
        self.addCleanup(os.remove, path)
        wc.write_output(wc.format_csv(artifact), path, as_csv=True)
        with open(path, "rb") as handle:
            data = handle.read()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("цветы".encode("utf-8"), data)

    def test_json_artifact_is_utf8_readable(self):
        artifact = self.artifact([{"phrase": "цветы", "count_raw": "1", "count": 1}])
        text = wc.format_json(artifact)
        self.assertIn("цветы", text)
        parsed = json.loads(text)
        self.assertEqual(parsed["phrase"], "доставка цветов")
        self.assertEqual(parsed["regions"], ["225"])
        self.assertEqual(
            parsed["source"], "yandex-cloud-search-api/v2/wordstat/topRequests"
        )


class JwtAndAuthTest(unittest.TestCase):
    def key(self):
        return {
            "key_id": "fake-key-id",
            "service_account_id": "fake-sa-id",
            "private_key": FAKE_PRIVATE_KEY,
        }

    def test_build_jwt_uses_ps256_header_and_short_ttl(self):
        captured = {}

        def fake_signer(signing_input, private_key_pem):
            captured["input"] = signing_input
            captured["key"] = private_key_pem
            return b"fake-signature"

        token = wc.build_jwt(
            self.key(), wc.DEFAULT_IAM_ENDPOINT, now=1_700_000_000, signer=fake_signer
        )
        header_b64, payload_b64, _ = token.split(".")
        header = json.loads(wc.base64.urlsafe_b64decode(header_b64 + "=="))
        payload = json.loads(wc.base64.urlsafe_b64decode(payload_b64 + "=="))
        self.assertEqual(header["alg"], "PS256")
        self.assertEqual(header["kid"], "fake-key-id")
        self.assertEqual(payload["iss"], "fake-sa-id")
        self.assertEqual(payload["aud"], wc.DEFAULT_IAM_ENDPOINT)
        self.assertEqual(payload["exp"] - payload["iat"], wc.JWT_TTL_SECONDS)
        self.assertLessEqual(payload["exp"] - payload["iat"], 3600)
        self.assertEqual(captured["key"], FAKE_PRIVATE_KEY)

    def test_get_iam_token_posts_jwt_and_returns_token(self):
        calls = []

        def fake_http(url, payload, headers, timeout):
            calls.append((url, payload, headers, timeout))
            return 200, json.dumps({"iamToken": FAKE_IAM_TOKEN})

        config = {"request_timeout_seconds": 12}
        token = wc.get_iam_token(
            config,
            self.key(),
            http=fake_http,
            signer=lambda data, key: b"sig",
            now=1_700_000_000,
        )
        self.assertEqual(token, FAKE_IAM_TOKEN)
        url, payload, _, timeout = calls[0]
        self.assertEqual(url, wc.DEFAULT_IAM_ENDPOINT)
        self.assertEqual(timeout, 12)
        self.assertIn("jwt", payload)
        self.assertNotIn("PRIVATE KEY", json.dumps(payload))

    def test_fetch_top_requests_sends_folder_regions_and_bearer(self):
        calls = []

        def fake_http(url, payload, headers, timeout):
            calls.append((url, payload, headers, timeout))
            return 200, json.dumps({"topRequests": [{"phrase": "x", "count": "1"}]})

        config = {"folder_id": "b1gfake", "request_timeout_seconds": 30}
        result = wc.fetch_top_requests(
            config, FAKE_IAM_TOKEN, "цветы", ["225", 213], limit=50, http=fake_http
        )
        url, payload, headers, _ = calls[0]
        self.assertEqual(url, wc.DEFAULT_TOP_REQUESTS_ENDPOINT)
        self.assertEqual(payload["folderId"], "b1gfake")
        self.assertEqual(payload["phrase"], "цветы")
        self.assertEqual(payload["regions"], ["225", "213"])
        self.assertEqual(payload["numPhrases"], "50")
        self.assertEqual(headers["Authorization"], "Bearer %s" % FAKE_IAM_TOKEN)
        self.assertEqual(result["topRequests"][0]["phrase"], "x")


class NoLiveNetworkTest(unittest.TestCase):
    """Сетевой шов должен резолвиться в момент вызова, иначе подмена не спасает."""

    def setUp(self):
        self.original_http = wc.http_post_json
        self.original_signer = wc.sign_ps256
        self.calls = []

        def blocked_http(url, payload, headers, timeout):
            self.calls.append(url)
            return 200, json.dumps(
                {
                    "iamToken": FAKE_IAM_TOKEN,
                    "topRequests": [{"phrase": "ключ", "count": "7"}],
                }
            )

        wc.http_post_json = blocked_http
        wc.sign_ps256 = lambda data, key: b"fake-signature"
        self.addCleanup(setattr, wc, "http_post_json", self.original_http)
        self.addCleanup(setattr, wc, "sign_ps256", self.original_signer)

    def test_module_level_patch_intercepts_iam_call(self):
        key = {
            "key_id": "fake-key-id",
            "service_account_id": "fake-sa-id",
            "private_key": FAKE_PRIVATE_KEY,
        }
        token = wc.get_iam_token({}, key)
        self.assertEqual(token, FAKE_IAM_TOKEN)
        self.assertEqual(self.calls, [wc.DEFAULT_IAM_ENDPOINT])

    def test_module_level_patch_intercepts_wordstat_call(self):
        wc.fetch_top_requests({"folder_id": "b1gfake"}, FAKE_IAM_TOKEN, "ключ", ["225"])
        self.assertEqual(self.calls, [wc.DEFAULT_TOP_REQUESTS_ENDPOINT])

    def test_cmd_top_runs_end_to_end_without_network(self):
        key_path = write_temp(
            json.dumps(
                {
                    "id": "fake-key-id",
                    "service_account_id": "fake-sa-id",
                    "private_key": FAKE_PRIVATE_KEY,
                }
            )
        )
        self.addCleanup(os.remove, key_path)
        config_path = write_temp(
            json.dumps(
                {
                    "backend": "cloud",
                    "folder_id": "b1gfake",
                    "authorized_key_file": key_path,
                    "endpoints": {
                        "iam_token": wc.DEFAULT_IAM_ENDPOINT,
                        "top_requests": wc.DEFAULT_TOP_REQUESTS_ENDPOINT,
                    },
                    "default_region_ids": [225],
                    "request_timeout_seconds": 30,
                }
            )
        )
        self.addCleanup(os.remove, config_path)
        out_path = write_temp("", suffix=".csv")
        self.addCleanup(os.remove, out_path)

        code = wc.main(
            [
                "top",
                "--phrase",
                "доставка цветов",
                "--region",
                "213",
                "--limit",
                "5",
                "--format",
                "csv",
                "--config",
                config_path,
                "--output",
                out_path,
            ]
        )
        self.assertEqual(code, wc.EXIT_OK)
        self.assertEqual(
            self.calls, [wc.DEFAULT_IAM_ENDPOINT, wc.DEFAULT_TOP_REQUESTS_ENDPOINT]
        )
        with open(out_path, encoding="utf-8-sig") as handle:
            body = handle.read()
        self.assertIn("topRequests,ключ,7,7,доставка цветов,213", body)


class SecretSafetyTest(unittest.TestCase):
    def test_scrub_removes_pem_block(self):
        text = "боль: %s конец" % FAKE_PRIVATE_KEY
        scrubbed = wc.scrub(text)
        self.assertNotIn("FAKE-KEY-MATERIAL", scrubbed)
        self.assertIn("REDACTED", scrubbed)

    def test_scrub_removes_bearer_token(self):
        scrubbed = wc.scrub("Authorization: Bearer %s" % FAKE_IAM_TOKEN)
        self.assertNotIn(FAKE_IAM_TOKEN, scrubbed)

    def test_403_error_mentions_role_and_hides_secrets(self):
        def fake_http(url, payload, headers, timeout):
            return 403, json.dumps({"message": "permission denied"})

        config = {"folder_id": "b1gfake"}
        with self.assertRaises(wc.WordstatError) as ctx:
            wc.fetch_top_requests(config, FAKE_IAM_TOKEN, "цветы", ["225"], http=fake_http)
        message = str(ctx.exception)
        self.assertEqual(ctx.exception.exit_code, wc.EXIT_AUTH)
        self.assertIn("search-api.webSearch.user", message)
        self.assertNotIn(FAKE_IAM_TOKEN, message)
        self.assertNotIn("PRIVATE KEY", message.upper())

    def test_401_from_iam_is_auth_error_without_jwt_in_message(self):
        def fake_http(url, payload, headers, timeout):
            return 401, "unauthenticated for jwt %s" % payload["jwt"]

        key = {
            "key_id": "fake-key-id",
            "service_account_id": "fake-sa-id",
            "private_key": FAKE_PRIVATE_KEY,
        }
        with self.assertRaises(wc.WordstatError) as ctx:
            wc.get_iam_token(
                {},
                key,
                http=fake_http,
                signer=lambda data, k: b"signature-bytes-long-enough-to-look-real",
                now=1_700_000_000,
            )
        message = wc.scrub(str(ctx.exception))
        self.assertEqual(ctx.exception.exit_code, wc.EXIT_AUTH)
        self.assertNotIn("fake-sa-id", message)
        self.assertNotIn("PRIVATE KEY", message.upper())

    def test_network_failure_gives_helpful_message(self):
        def failing_http(url, payload, headers, timeout):
            raise wc.WordstatError(
                "Сеть недоступна при обращении к %s: timed out" % url, wc.EXIT_NETWORK
            )

        with self.assertRaises(wc.WordstatError) as ctx:
            wc.fetch_top_requests(
                {"folder_id": "b1gfake"}, FAKE_IAM_TOKEN, "цветы", None, http=failing_http
            )
        self.assertEqual(ctx.exception.exit_code, wc.EXIT_NETWORK)
        self.assertIn("Сеть недоступна", str(ctx.exception))

    def test_429_and_500_map_to_network_exit_code(self):
        for status in (429, 500, 503):
            def fake_http(url, payload, headers, timeout, status=status):
                return status, "{}"

            with self.assertRaises(wc.WordstatError) as ctx:
                wc.fetch_top_requests(
                    {"folder_id": "b1gfake"}, FAKE_IAM_TOKEN, "ф", None, http=fake_http
                )
            self.assertEqual(ctx.exception.exit_code, wc.EXIT_NETWORK)

    def test_authorized_key_missing_fields_reports_without_dumping_file(self):
        path = write_temp(json.dumps({"private_key": FAKE_PRIVATE_KEY}))
        self.addCleanup(os.remove, path)
        with self.assertRaises(wc.WordstatError) as ctx:
            wc.load_authorized_key(path)
        message = str(ctx.exception)
        self.assertIn("service_account_id", message)
        self.assertNotIn("FAKE-KEY-MATERIAL", message)


if __name__ == "__main__":
    unittest.main()
