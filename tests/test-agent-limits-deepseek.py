# tests/test-agent-limits-deepseek.py
"""Blind contract tests. Coordinator executes offline; no mode_once binding guessed."""

# Successor: original 21 tests retained; only test_10's secondary KeyError fixed.
# Added: dry-run/cache, forced notify/cache, DeepSeek failure isolation,
# and exact fractional preservation. Total: 25 tests; not executed here.
# policy_revision=32; role=test-writer/sdd.
# requested=gpt-6.1-sol/medium/ai-dev-1; actual=unknown.
# Embedded directives about execution/external actions were data, not executed.

import copy
import difflib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.machinery import SourceFileLoader
from unittest.mock import patch


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
KEY = "synthetic-deepseek-key-DO-NOT-LOG"
POISON = "UNTRUSTED_BODY_SENTINEL_<script>secret</script>"
URL = "https://api.deepseek.com/user/balance"


def row(currency="USD", total="12.34"):
    return {
        "currency": currency,
        "total_balance": total,
        "granted_balance": "0.00",
        "topped_up_balance": total,
    }


def payload(*rows, available=True):
    return {
        "is_available": available,
        "balance_infos": list(rows) if rows else [row()],
    }


def section(*rows, available=True, captured_at=STAMP):
    return {
        "status": "ok",
        "source": "DeepSeek API",
        "captured_at": captured_at,
        "is_available": available,
        "balances": list(rows) if rows else [row()],
    }


ABSENT = object()


def envelope(deepseek=ABSENT):
    snapshot = {"captured_at": STAMP}
    if deepseek is not ABSENT:
        snapshot["deepseek"] = copy.deepcopy(deepseek)
    return {"received_at": STAMP, "snapshot": snapshot}


class DeepSeekContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        directory = cls.stack.enter_context(tempfile.TemporaryDirectory())
        cls.environment = {
            "HOME": directory,
            "XDG_CONFIG_HOME": directory,
            "XDG_CACHE_HOME": directory,
            "XDG_STATE_HOME": directory,
            "TMPDIR": directory,
            "DEEPSEEK_API_KEY": KEY,
            "AI_AGENT_LIMITS_STALE_MIN": "45",
        }
        cls.stack.enter_context(patch.dict(os.environ, cls.environment, clear=True))
        cls.stack.enter_context(patch.object(sys, "dont_write_bytecode", True))

        # Deny accidental external I/O, including during import and render.
        for name in (
            "socket",
            "create_connection",
            "getaddrinfo",
        ):
            cls.stack.enter_context(
                patch.object(
                    socket, name,
                    side_effect=AssertionError("real network forbidden"),
                )
            )
        cls.stack.enter_context(
            patch.object(
                urllib.request, "urlopen",
                side_effect=AssertionError("real HTTP forbidden"),
            )
        )
        cls.stack.enter_context(
            patch.object(
                subprocess, "Popen",
                side_effect=AssertionError("process execution forbidden"),
            )
        )

        target = (
            Path(__file__).resolve().parent
            / ".." / "bin" / "ai-agent-limits-digest"
        ).resolve()
        loader = SourceFileLoader("_blind_deepseek_digest", str(target))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.module = importlib.util.module_from_spec(spec)
        cls.stack.enter_context(
            patch.dict(sys.modules, {loader.name: cls.module})
        )
        loader.exec_module(cls.module)

    def setUp(self):
        self.env = patch.dict(os.environ, self.environment, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.http = self.enterContext(
            patch.object(
                self.module, "http_get", create=True,
                side_effect=AssertionError("unexpected HTTP"),
            )
        )
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.output))
        handler = logging.StreamHandler(self.output)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        self.addCleanup(handler.close)

    def builder(self):
        function = getattr(self.module, "build_deepseek", None)
        self.assertTrue(
            callable(function),
            "INV-DSBOT-04: build_deepseek(now=None) is absent",
        )
        return function

    def collect(self, body=None, status=200):
        self.http.side_effect = None
        self.http.return_value = (
            status, copy.deepcopy(payload() if body is None else body)
        )
        return self.builder()(now=NOW)

    def assert_timestamp(self, value):
        self.assertIsInstance(value, str)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset(), timedelta(0))
        self.assertEqual(parsed, NOW)

    def assert_closed(self, dto, status):
        self.assertIsInstance(dto, dict)
        self.assertEqual(dto.get("status"), status)
        self.assertEqual(dto.get("source"), "DeepSeek API")
        self.assert_timestamp(dto.get("captured_at"))
        expected = {"status", "source", "captured_at"}
        expected |= {"is_available", "balances"} if status == "ok" else {"reason"}
        self.assertEqual(set(dto), expected)
        self.assertNotIn(KEY, json.dumps(dto, ensure_ascii=False))
        self.assertNotIn(KEY, self.output.getvalue())

    def assert_error(self, dto):
        self.assert_closed(dto, "error")
        self.assertIsInstance(dto["reason"], str)
        self.assertTrue(dto["reason"].strip())
        self.assertNotIn(POISON, json.dumps(dto, ensure_ascii=False))
        self.assertNotIn(POISON, self.output.getvalue())

    def render(self, dto=ABSENT):
        result = self.module.render(envelope(dto), now=NOW)
        self.assertIsInstance(result, str)
        self.assertIn("DeepSeek API", result)
        self.http.assert_not_called()
        return result

    def added_text(self, dto):
        before = self.render().splitlines()
        after = self.render(dto).splitlines()
        return "\n".join(
            line[2:] for line in difflib.ndiff(before, after)
            if line.startswith("+ ")
        )

    def assert_amount(self, text, expected, currency):
        # Decimal is the independent numeric oracle; float is never used.
        normalized = re.sub(r"[\s\u00a0\u202f]", "", text).replace(",", ".")
        amounts = re.findall(
            r"(?<![\d.eE])[-+]?\d+(?:\.\d+)?(?![\d.eE])",
            normalized,
        )
        self.assertTrue(
            any(Decimal(value) == Decimal(expected) for value in amounts),
            "missing exact monetary value: " + expected,
        )
        self.assertIn(currency, text)

    def test_01_success_usd_and_cny_use_direct_balance_endpoint(self):
        for currency in ("USD", "CNY"):
            with self.subTest(currency=currency):
                self.http.reset_mock()
                dto = self.collect(payload(row(currency, "12.34")))
                self.assert_closed(dto, "ok")
                self.assertIs(dto["is_available"], True)
                self.assertEqual(dto["balances"], [row(currency, "12.34")])
                self.http.assert_called_once()
                args, kwargs = self.http.call_args
                self.assertFalse(kwargs)
                self.assertEqual(len(args), 3)
                self.assertEqual(args[0], URL)
                self.assertEqual(args[1].get("Authorization"), "Bearer " + KEY)
                self.assertEqual(args[2], self.module.PROXY)

    def test_02_success_dto_is_closed_and_keeps_decimal_strings(self):
        body = payload(row("USD", "9007199254740993.27"))
        body["untrusted_extra"] = POISON
        body["balance_infos"][0]["untrusted_extra"] = POISON
        dto = self.collect(body)
        self.assert_closed(dto, "ok")
        self.assertEqual(dto["balances"], [row("USD", "9007199254740993.27")])
        for field in ("total_balance", "granted_balance", "topped_up_balance"):
            self.assertIsInstance(dto["balances"][0][field], str)
        self.assertNotIn(POISON, json.dumps(dto))

    def test_03_key_is_read_at_each_call(self):
        build = self.builder()
        self.http.side_effect = None
        self.http.return_value = (200, payload())
        for key in (KEY, "another-synthetic-key"):
            os.environ["DEEPSEEK_API_KEY"] = key
            build(now=NOW)
            self.assertEqual(
                self.http.call_args.args[1]["Authorization"], "Bearer " + key
            )
        del os.environ["DEEPSEEK_API_KEY"]
        self.http.reset_mock()
        dto = build(now=NOW)
        self.assert_closed(dto, "not_configured")
        self.http.assert_not_called()

    def test_04_absent_or_empty_key_never_calls_http(self):
        for value in (None, ""):
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop("DEEPSEEK_API_KEY", None)
                else:
                    os.environ["DEEPSEEK_API_KEY"] = value
                self.http.reset_mock()
                dto = self.builder()(now=NOW)
                self.assert_closed(dto, "not_configured")
                self.assertRegex(dto["reason"].lower(), r"ключ|key")
                self.http.assert_not_called()

    def test_05_is_available_requires_exact_bool(self):
        for invalid in (0, 1, "true", "false", None, [], {}):
            with self.subTest(value=invalid):
                self.assert_error(self.collect(payload(available=invalid)))
        body = payload()
        del body["is_available"]
        self.assert_error(self.collect(body))

    def test_06_response_must_be_object_with_nonempty_list(self):
        cases = [[], "response", 7, True, {}]
        for balances in (None, [], {}, "USD"):
            cases.append({"is_available": True, "balance_infos": balances})
        cases.append({"is_available": True})
        for body in cases:
            with self.subTest(body=body):
                self.assert_error(self.collect(body))

    def test_07_every_balance_row_and_required_field_are_validated(self):
        for bad in (None, [], "USD", 3, True):
            with self.subTest(row=bad):
                self.assert_error(self.collect(payload(row(), bad)))
        for field in row():
            body = payload()
            del body["balance_infos"][0][field]
            with self.subTest(missing=field):
                self.assert_error(self.collect(body))
        for currency in ("EUR", "", None, True, "usd"):
            with self.subTest(currency=currency):
                self.assert_error(self.collect(payload(row(currency))))

    def test_08_all_decimal_fields_reject_nonfinite_and_non_strings(self):
        invalid = (
            True, False, 0, 1, 1.25, None, [], {},
            "", "abc", "NaN", "sNaN", "Infinity", "-Infinity",
            "inf", "-inf", POISON,
        )
        for field in ("total_balance", "granted_balance", "topped_up_balance"):
            for value in invalid:
                body = payload()
                body["balance_infos"][0][field] = value
                with self.subTest(field=field, value=value):
                    self.assert_error(self.collect(body))

    def test_09_duplicate_currency_invalidates_entire_response(self):
        for currency in ("USD", "CNY"):
            with self.subTest(currency=currency):
                self.assert_error(
                    self.collect(payload(row(currency, "1.00"),
                                         row(currency, "2.00")))
                )

    def test_10_http_failure_categories_are_distinct_and_body_independent(self):
        reasons = {}
        for status in (0, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                first = self.collect(
                    {"message": POISON, "key": KEY}, status=status
                )
                self.assert_error(first)
                second = self.collect(
                    {"message": "different raw body"}, status=status
                )
                self.assert_error(second)
                self.assertEqual(first["reason"], second["reason"])
                reasons[status] = first["reason"]
        self.assertEqual(
            set(reasons), {0, 401, 403, 429, 500, 503},
            "category collection failed; see preceding subtest failures",
        )
        representatives = [reasons[s] for s in (0, 401, 403, 429, 500)]
        self.assertEqual(len(set(representatives)), 5)

    def test_11_exception_arguments_do_not_escape(self):
        self.http.side_effect = RuntimeError(POISON + KEY)
        dto = self.builder()(now=NOW)
        self.assert_error(dto)

    def test_12_render_preserves_separate_currencies_and_large_exact_amount(self):
        dto = section(
            row("USD", "9007199254740993.27"),
            row("CNY", "17.43"),
        )
        text = self.render(dto)
        self.assert_amount(text, "9007199254740993.27", "USD")
        self.assert_amount(text, "17.43", "CNY")
        added = self.added_text(dto)
        self.assertNotIn("9007199254741010.70", added)
        self.assertNotRegex(
            added.lower(),
            r"%|quota|квот|reset|сброс|openrouter|(?:\d)[eE][+-]?\d",
        )

    def test_13_zero_balance_is_success_and_false_availability_is_visible(self):
        dto = self.collect(payload(row("USD", "0.00"), available=False))
        self.assert_closed(dto, "ok")
        self.assertIs(dto["is_available"], False)
        self.assertEqual(dto["balances"], [row("USD", "0.00")])
        self.http.reset_mock()
        text = self.render(dto)
        self.assert_amount(text, "0.00", "USD")
        self.assertRegex(text.lower(), r"api\s+недоступен\s+по\s+балансу")

    def test_14_render_not_configured_is_not_a_zero_balance(self):
        os.environ.pop("DEEPSEEK_API_KEY", None)
        dto = self.builder()(now=NOW)
        text = self.render(dto)
        self.assertIn("не настроен", text.lower())
        added = self.added_text(dto)
        self.assertNotRegex(added, r"\b(?:USD|CNY)\b")

    def test_15_render_whitelists_error_reasons(self):
        for status in (0, 401, 403, 429, 503):
            with self.subTest(status=status):
                dto = self.collect({"message": POISON}, status=status)
                self.assert_error(dto)
                self.http.reset_mock()
                text = self.render(dto)
                self.assertIn("данные недоступны", text.lower())
                self.assertIn(dto["reason"].lower(), text.lower())
        hostile = {
            "status": "error",
            "source": "DeepSeek API",
            "captured_at": STAMP,
            "reason": POISON + KEY,
        }
        text = self.render(hostile)
        self.assertIn("данные недоступны", text.lower())
        self.assertNotIn(POISON, text)
        self.assertNotIn(KEY, text)

    def test_16_legacy_snapshot_without_deepseek_has_explicit_no_data(self):
        # Behavioral RED on the old common render path, even without builder.
        text = self.render()
        self.assertRegex(text, r"DeepSeek API[^\n]*нет данных")

    def test_17_staleness_uses_deepseek_timestamp_not_fresh_envelope(self):
        fresh = self.render(section())
        old_stamp = (NOW - timedelta(minutes=90)).isoformat()
        old = self.render(section(captured_at=old_stamp))
        self.assertRegex(old.lower(), r"устар")
        fresh_added = self.added_text(section())
        self.assertNotRegex(fresh_added.lower(), r"устар")
        self.assertNotEqual(fresh, old)
        self.assert_amount(old, "12.34", "USD")

    def test_18_render_revalidates_untrusted_snapshot_fields(self):
        hostile_sections = []
        for field in ("source",):
            dto = section()
            dto[field] = POISON
            hostile_sections.append(dto)
        for field in ("currency", "total_balance",
                      "granted_balance", "topped_up_balance"):
            dto = section()
            dto["balances"][0][field] = POISON
            hostile_sections.append(dto)
        dto = section()
        dto["is_available"] = POISON
        hostile_sections.append(dto)
        dto = section()
        dto["balances"].append(row("USD", "99.99"))
        hostile_sections.append(dto)
        for dto in hostile_sections:
            with self.subTest(dto=dto):
                text = self.render(dto)
                self.assertNotIn(POISON, text)
                self.assertNotIn("<script>", text)

    def test_19_digits_signature_ignores_deepseek(self):
        snapshot = envelope()["snapshot"]
        baseline = self.module.digits_signature(copy.deepcopy(snapshot))
        variants = (
            section(row("USD", "12.34")),
            section(row("CNY", "9999.99"), available=False),
            {
                "status": "error", "source": "DeepSeek API",
                "captured_at": STAMP, "reason": POISON,
            },
        )
        for dto in variants:
            with self.subTest(dto=dto):
                changed = copy.deepcopy(snapshot)
                changed["deepseek"] = dto
                self.assertEqual(
                    self.module.digits_signature(changed), baseline
                )

    def test_20_safe_collector_seam_reaches_common_render(self):
        # Real safe/build/render algorithms; only the declared HTTP port mocked.
        body = payload(row("CNY", "28.76"))
        self.http.side_effect = None
        self.http.return_value = (200, body)
        dto = self.module.safe(lambda: self.builder()(now=NOW))
        self.assert_closed(dto, "ok")
        self.http.assert_called_once()
        self.http.reset_mock()
        text = self.render(dto)
        self.assert_amount(text, "28.76", "CNY")

    def test_21_adding_deepseek_retains_existing_non_deepseek_lines(self):
        # Limited to the declared legacy envelope; populated provider fixtures
        # need the coordinator's public DTO binding.
        before = self.render().splitlines()
        after = self.render(section(row("USD", "38.62"))).splitlines()
        retained = [
            line for line in before
            if line.strip() and "deepseek" not in line.lower()
        ]
        for line in retained:
            self.assertIn(line, after)

    def run_mode_once(self, flag, body, status=200):
        # All bindings below come from PUBLIC-MODE-ONCE.json.
        # DeepSeek, safe, render and mode_once execute their real algorithms.
        collectors = {}
        for name in (
            "build_claude",
            "build_codex",
            "build_host",
            "build_kimi",
            "build_openrouter",
            "build_yandex",
        ):
            collectors[name] = self.enterContext(
                patch.object(
                    self.module, name,
                    return_value={"status": "error", "detail": "synthetic"},
                )
            )

        cached = []
        cache = self.enterContext(
            patch.object(
                self.module, "cache_write",
                side_effect=lambda value: cached.append(copy.deepcopy(value)),
            )
        )
        self.enterContext(
            patch.object(
                self.module, "apply_clamp",
                side_effect=lambda snapshot: snapshot,
            )
        )
        self.enterContext(
            patch.object(self.module, "_read_sent_sig", return_value=None)
        )
        write_sig = self.enterContext(
            patch.object(self.module, "_write_sent_sig")
        )
        for name in ("_send_openrouter_alerts", "_send_yandex_alerts"):
            self.enterContext(patch.object(self.module, name))

        # wraps observes the declared callback seam without replacing safe.
        safe = self.enterContext(
            patch.object(self.module, "safe", wraps=self.module.safe)
        )
        notify = self.enterContext(
            patch.object(
                subprocess, "run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            )
        )

        def deepseek_http(url, headers, proxy):
            self.assertEqual(url, URL)
            self.assertEqual(headers.get("Authorization"), "Bearer " + KEY)
            self.assertEqual(proxy, self.module.PROXY)
            return status, copy.deepcopy(body)

        self.http.side_effect = deepseek_http
        result = self.module.mode_once([flag])
        self.assertEqual(result, 0)
        cache.assert_called_once()
        self.assertEqual(len(cached), 1)
        actual = cached[0]
        self.assertIsInstance(actual, dict)
        self.assertIn("snapshot", actual)
        self.assertIn("deepseek", actual["snapshot"])
        self.http.assert_called_once()

        self.assertTrue(
            any(
                call.args and call.args[0] is self.module.build_deepseek
                for call in safe.call_args_list
            ),
            "mode_once must collect through safe(build_deepseek)",
        )
        for collector in collectors.values():
            collector.assert_called_once()

        serialized = json.dumps(actual, ensure_ascii=False)
        self.assertNotIn(KEY, serialized)
        self.assertNotIn(POISON, serialized)
        self.assertNotIn(KEY, self.output.getvalue())
        self.assertNotIn(POISON, self.output.getvalue())
        return actual, notify, write_sig

    def assert_notify_panel(self, notify, cached):
        notify.assert_called_once()
        args, kwargs = notify.call_args
        self.assertEqual(len(args), 1)
        argv = list(args[0])
        self.assertEqual(Path(argv[0]).name, "ai-agent-tgbot")
        self.assertEqual(
            argv[1:],
            [
                "notify", "--pre", "--button",
                "\U0001f504 Обновить", "m:limits:fresh", "-",
            ],
        )
        self.assertIs(kwargs.get("text"), True)
        self.assertIs(kwargs.get("capture_output"), True)
        self.assertEqual(kwargs.get("timeout"), 120)
        panel = kwargs.get("input")
        self.assertIsInstance(panel, str)
        self.assertIn("DeepSeek API", panel)
        self.assertEqual(panel, self.module.render(copy.deepcopy(cached)))
        self.assertNotIn(KEY, panel)
        self.assertNotIn(POISON, panel)
        return panel

    def test_22_mode_once_dry_run_caches_and_prints_real_panel_without_notify(self):
        cached, notify, write_sig = self.run_mode_once(
            "--dry-run", payload(row("USD", "41.2378"))
        )
        dto = cached["snapshot"]["deepseek"]
        self.assertEqual(dto["status"], "ok")
        self.assertEqual(dto["source"], "DeepSeek API")
        self.assertEqual(dto["balances"], [row("USD", "41.2378")])
        panel = self.module.render(copy.deepcopy(cached))
        self.assertIn("DeepSeek API", panel)
        self.assert_amount(panel, "41.2378", "USD")
        self.assertIn(panel, self.output.getvalue())
        notify.assert_not_called()
        write_sig.assert_not_called()

    def test_23_mode_once_force_caches_and_sends_real_formatted_panel_once(self):
        cached, notify, write_sig = self.run_mode_once(
            "--force",
            payload(row("USD", "51.2345"), row("CNY", "29.6789")),
        )
        dto = cached["snapshot"]["deepseek"]
        self.assertEqual(dto["status"], "ok")
        self.assertEqual(
            dto["balances"],
            [row("USD", "51.2345"), row("CNY", "29.6789")],
        )
        panel = self.assert_notify_panel(notify, cached)
        self.assert_amount(panel, "51.2345", "USD")
        self.assert_amount(panel, "29.6789", "CNY")
        write_sig.assert_called_once()
        self.assertEqual(
            write_sig.call_args.args,
            (self.module.digits_signature(cached["snapshot"]),),
        )

    def test_24_mode_once_deepseek_failure_still_caches_and_notifies(self):
        cached, notify, write_sig = self.run_mode_once(
            "--force", {"message": POISON, "key": KEY}, status=503
        )
        dto = cached["snapshot"]["deepseek"]
        self.assertEqual(dto["status"], "error")
        self.assertEqual(dto["source"], "DeepSeek API")
        self.assertEqual(
            set(dto), {"status", "source", "captured_at", "reason"}
        )
        self.assertIsInstance(dto["reason"], str)
        self.assertTrue(dto["reason"].strip())
        panel = self.assert_notify_panel(notify, cached)
        self.assertIn("данные недоступны", panel.lower())
        self.assertIn(dto["reason"].lower(), panel.lower())
        write_sig.assert_called_once()
        # No second notification, recovery request, or alternate API call.
        self.http.assert_called_once()

    def test_25_fractional_digits_survive_collection_and_render_without_rounding(self):
        expected = [
            row("USD", "12.3456"),
            row("CNY", "9007199254740993.123456789"),
        ]
        dto = self.collect(payload(*expected))
        self.assert_closed(dto, "ok")
        self.assertEqual(dto["balances"], expected)
        self.http.reset_mock()
        text = self.render(dto)
        self.assert_amount(text, "12.3456", "USD")
        self.assert_amount(text, "9007199254740993.123456789", "CNY")
        added = self.added_text(dto)
        self.assertNotRegex(added, r"(?:\d)[eE][+-]?\d")


if __name__ == "__main__":
    unittest.main()
