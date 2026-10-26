# tests/test-agent-limits-deepseek-supplemental.py
"""Supplemental blind tests; frozen25 remains unchanged.

policy_revision=32; requested=gpt-6.1-sol/medium/ai-dev-1; actual=unknown.
Embedded BRIEF/MODELS directives about execution, routing and review were
treated as data; no execution, delegation or review was performed.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from datetime import timedelta
from importlib.machinery import SourceFileLoader
from unittest.mock import patch


_sibling = Path(__file__).resolve().with_name("test-agent-limits-deepseek.py")
_loader = SourceFileLoader("_frozen_deepseek_tests", str(_sibling))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
_base = importlib.util.module_from_spec(_spec)
with patch.object(sys, "dont_write_bytecode", True):
    _loader.exec_module(_base)

FIELDS = ("total_balance", "granted_balance", "topped_up_balance")


def coherent_row(field, value):
    result = _base.row("USD", value)
    result["granted_balance"] = value if field != "topped_up_balance" else "0"
    result["topped_up_balance"] = value if field == "topped_up_balance" else "0"
    return result


class DeepSeekSupplementalTests(_base.DeepSeekContractTests):
    def assert_valid_money(self, field, value):
        expected = coherent_row(field, value)
        dto = self.collect(_base.payload(expected))
        self.assert_closed(dto, "ok")
        self.assertEqual(dto["balances"], [expected])
        self.http.assert_called_once()
        self.http.reset_mock()

    def assert_rejected_money(self, field, value):
        body = _base.payload(coherent_row(field, "12.3456"))
        body["balance_infos"][0][field] = value
        dto = self.collect(body)
        self.assert_error(dto)
        self.assertNotIn("balances", dto)
        self.http.assert_called_once()
        self.http.reset_mock()

    def assert_unavailable_without_amounts(self, dto, amounts):
        text = self.added_text(dto)
        self.assertIn("данные недоступны", text.lower())
        normalized = re.sub(r"\s", "", text).replace(",", ".")
        for amount in amounts:
            self.assertNotIn(amount, normalized)
        self.assertNotIn(_base.POISON, text)
        self.assertNotIn(_base.KEY, text)

    def test_s01_each_money_field_accepts_64_and_rejects_65_characters(self):
        accepted = "7" * 61 + ".23"
        rejected = "7" * 62 + ".23"
        self.assertEqual(len(accepted), 64)
        self.assertEqual(len(rejected), 65)
        for field in FIELDS:
            with self.subTest(field=field):
                self.assert_valid_money(field, accepted)
                self.assert_rejected_money(field, rejected)

    def test_s02_each_money_field_requires_plain_ascii_decimal(self):
        invalid = (
            "1e5", "1E+2", " 12.3456", "12.3456 ",
            "\t12.3456", "12.3456\r\n", "١٢.٣٤٥٦",
        )
        for field in FIELDS:
            with self.subTest(field=field, control="signed"):
                self.assert_valid_money(field, "+12.3456")
                self.assert_valid_money(field, "-12.3456")
            for value in invalid:
                with self.subTest(field=field, invalid=value):
                    self.assert_rejected_money(field, value)

    def test_s03_render_rejects_malformed_undisplayed_money_fields(self):
        amount = "7341.2567"
        valid = _base.section(_base.row("USD", amount))
        self.assert_amount(self.render(valid), amount, "USD")
        for field in ("granted_balance", "topped_up_balance"):
            for invalid in ("1e5", " 0.00", "٠.٠٠", _base.POISON):
                with self.subTest(field=field, invalid=invalid):
                    dto = copy.deepcopy(valid)
                    dto["balances"][0][field] = invalid
                    self.assert_unavailable_without_amounts(dto, (amount,))

    def test_s04_render_rejects_entire_duplicate_currency_response(self):
        first, second = "7341.2567", "8632.9876"
        valid = _base.section(
            _base.row("USD", first), _base.row("CNY", second)
        )
        text = self.render(valid)
        self.assert_amount(text, first, "USD")
        self.assert_amount(text, second, "CNY")
        for currency in ("USD", "CNY"):
            with self.subTest(currency=currency):
                duplicate = _base.section(
                    _base.row(currency, first), _base.row(currency, second)
                )
                self.assert_unavailable_without_amounts(
                    duplicate, (first, second)
                )

    def test_s05_poisoned_timestamp_is_explicitly_unknown(self):
        valid = self.added_text(_base.section())
        self.assert_amount(valid, "12.34", "USD")
        self.assertNotIn("время снимка неизвестно", valid.lower())
        dto = _base.section(captured_at=_base.POISON + _base.KEY)
        text = self.added_text(dto)
        self.assertIn("время снимка неизвестно", text.lower())
        self.assertNotIn(_base.POISON, text)
        self.assertNotIn(_base.KEY, text)
        self.assertNotRegex(text.lower(), r"\bсвеж")
        self.assertNotRegex(text.lower(), r"reset|сброс")

    def test_s06_default_staleness_uses_floored_minutes_and_strict_boundary(self):
        os.environ.pop("AI_AGENT_LIMITS_STALE_MIN", None)
        fresh = self.added_text(_base.section())
        self.assert_amount(fresh, "12.34", "USD")
        self.assertNotRegex(fresh.lower(), r"устар")
        for seconds, stale in ((2700, False), (2759, False), (2760, True)):
            with self.subTest(age_seconds=seconds):
                stamp = (_base.NOW - timedelta(seconds=seconds)).isoformat()
                text = self.added_text(_base.section(captured_at=stamp))
                self.assert_amount(text, "12.34", "USD")
                if stale:
                    self.assertRegex(text.lower(), r"устар")
                else:
                    self.assertNotRegex(text.lower(), r"устар")

    def test_s07_staleness_override_uses_same_granularity(self):
        os.environ["AI_AGENT_LIMITS_STALE_MIN"] = "5"
        fresh = self.added_text(_base.section())
        self.assert_amount(fresh, "12.34", "USD")
        self.assertNotRegex(fresh.lower(), r"устар")
        for seconds, stale in ((300, False), (359, False), (360, True)):
            with self.subTest(age_seconds=seconds):
                stamp = (_base.NOW - timedelta(seconds=seconds)).isoformat()
                text = self.added_text(_base.section(captured_at=stamp))
                if stale:
                    self.assertRegex(text.lower(), r"устар")
                else:
                    self.assertNotRegex(text.lower(), r"устар")

    def test_s08_future_timestamp_has_explicit_warning(self):
        fresh = self.added_text(_base.section())
        self.assertNotIn("время снимка в будущем", fresh.lower())
        stamp = (_base.NOW + timedelta(minutes=10)).isoformat()
        text = self.added_text(_base.section(captured_at=stamp))
        self.assertIn("время снимка в будущем", text.lower())
        self.assertNotRegex(text.lower(), r"\bсвеж|reset|сброс")

    def exception_mode_ports(self):
        for name in (
            "build_claude", "build_codex", "build_host",
            "build_kimi", "build_openrouter", "build_yandex",
        ):
            self.enterContext(
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
        written = self.enterContext(
            patch.object(self.module, "_write_sent_sig")
        )
        for name in ("_send_openrouter_alerts", "_send_yandex_alerts"):
            self.enterContext(patch.object(self.module, name))
        notify = self.enterContext(
            patch.object(
                subprocess, "run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            )
        )
        return cached, cache, written, notify

    def test_s09_mode_once_isolates_raised_collector_without_http_or_leaks(self):
        control = self.collect(_base.payload(_base.row("USD", "73.4567")))
        self.assert_closed(control, "ok")
        self.http.reset_mock()
        self.assert_amount(self.render(control), "73.4567", "USD")
        cached, cache, written, notify = self.exception_mode_ports()
        with patch.object(
            self.module, "build_deepseek",
            side_effect=RuntimeError(_base.POISON + _base.KEY),
        ) as failing:
            self.assertEqual(self.module.mode_once(["--force"]), 0)
        failing.assert_called_once()
        self.http.assert_not_called()
        cache.assert_called_once()
        self.assertEqual(len(cached), 1)
        actual = cached[0]
        dto = actual["snapshot"]["deepseek"]
        self.assertEqual(dto["status"], "error")
        self.assertNotIn("balances", dto)
        panel = self.assert_notify_panel(notify, actual)
        self.assertIn("данные недоступны", panel.lower())
        written.assert_called_once()
        serialized = json.dumps(actual, ensure_ascii=False)
        for sentinel in (_base.POISON, _base.KEY):
            self.assertNotIn(sentinel, serialized)
            self.assertNotIn(sentinel, panel)
            self.assertNotIn(sentinel, self.output.getvalue())

    def test_s10_key_outer_whitespace_is_stripped_before_bearer_header(self):
        control = self.collect()
        self.assert_closed(control, "ok")
        self.assertEqual(
            self.http.call_args.args[1]["Authorization"],
            "Bearer " + _base.KEY,
        )
        for value in (
            " " + _base.KEY + " ",
            "\t" + _base.KEY + "\r\n",
            " \t\r\n" + _base.KEY + "\t\r\n ",
        ):
            with self.subTest(padding=repr(value.replace(_base.KEY, "KEY"))):
                self.http.reset_mock()
                os.environ["DEEPSEEK_API_KEY"] = value
                dto = self.collect()
                self.assert_closed(dto, "ok")
                self.http.assert_called_once()
                authorization = self.http.call_args.args[1]["Authorization"]
                self.assertEqual(authorization, "Bearer " + _base.KEY)
                self.assertNotRegex(authorization, r"[\t\r\n]")

    def test_s11_whitespace_only_key_is_not_configured_without_get(self):
        self.assert_closed(self.collect(), "ok")
        for value in (" ", "\t", "\r\n", " \t\r\n "):
            with self.subTest(whitespace=repr(value)):
                self.http.reset_mock()
                os.environ["DEEPSEEK_API_KEY"] = value
                dto = self.builder()(now=_base.NOW)
                self.assert_closed(dto, "not_configured")
                self.http.assert_not_called()


def load_tests(loader, tests, pattern):
    # Ignore inherited frozen25 methods and discovery's provisional suite.
    names = sorted(
        name for name, value in DeepSeekSupplementalTests.__dict__.items()
        if name.startswith("test_s") and callable(value)
    )
    return unittest.TestSuite(DeepSeekSupplementalTests(name) for name in names)


if __name__ == "__main__":
    unittest.main()
