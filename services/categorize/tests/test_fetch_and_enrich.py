import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

import categorize.main as main_module
from categorize.main import _enrich, _fetch_rules_and_aliases


def _http_mock(rules_data, merchants_data):
    """Return a patched httpx.Client class whose context manager yields a mock client."""
    rules_resp = MagicMock()
    rules_resp.raise_for_status.return_value = rules_resp
    rules_resp.json.return_value = rules_data

    merchants_resp = MagicMock()
    merchants_resp.raise_for_status.return_value = merchants_resp
    merchants_resp.json.return_value = merchants_data

    mock_client = MagicMock()
    mock_client.get.side_effect = [rules_resp, merchants_resp]

    mock_cls = MagicMock()
    mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_cls


# ── _fetch_rules_and_aliases ──────────────────────────────────────────────────

class TestFetchRulesAndAliases:
    def test_cache_hit_skips_http(self):
        main_module._cached_rules = [{"name": "cached"}]
        main_module._cached_aliases = [{"alias": "cached"}]
        main_module._cache_expires_at = float("inf")

        with patch("categorize.main.httpx.Client") as mock_cls:
            rules, aliases = _fetch_rules_and_aliases()

        mock_cls.assert_not_called()
        assert rules == [{"name": "cached"}]
        assert aliases == [{"alias": "cached"}]

    def test_cache_miss_fetches_from_http(self):
        rules_data = [{"name": "r1", "pattern": "NETFLIX", "matchType": "Contains",
                       "category": "Subscriptions", "priority": 1}]
        merchants_data = [
            {"canonicalName": "Netflix", "defaultCategory": "Subscriptions",
             "aliases": [{"pattern": "NETFLIX", "matchType": "Contains"}]}
        ]

        with patch("categorize.main.httpx.Client", _http_mock(rules_data, merchants_data)):
            rules, aliases = _fetch_rules_and_aliases()

        assert len(rules) == 1
        assert rules[0]["category"] == "Subscriptions"
        assert len(aliases) == 1
        assert aliases[0]["merchantName"] == "Netflix"
        assert aliases[0]["defaultCategory"] == "Subscriptions"
        assert aliases[0]["pattern"] == "NETFLIX"

    def test_flattens_multiple_aliases_per_merchant(self):
        merchants_data = [
            {
                "canonicalName": "MENY",
                "defaultCategory": "Groceries",
                "aliases": [
                    {"pattern": "MENY", "matchType": "StartsWith"},
                    {"pattern": "MENY MARKED", "matchType": "Contains"},
                ],
            }
        ]

        with patch("categorize.main.httpx.Client", _http_mock([], merchants_data)):
            _, aliases = _fetch_rules_and_aliases()

        assert len(aliases) == 2
        assert all(a["merchantName"] == "MENY" for a in aliases)
        assert all(a["defaultCategory"] == "Groceries" for a in aliases)

    def test_multiple_merchants_all_flattened(self):
        merchants_data = [
            {"canonicalName": "Netflix", "defaultCategory": "Subscriptions",
             "aliases": [{"pattern": "NETFLIX", "matchType": "Contains"}]},
            {"canonicalName": "MENY", "defaultCategory": "Groceries",
             "aliases": [{"pattern": "MENY", "matchType": "StartsWith"}]},
        ]

        with patch("categorize.main.httpx.Client", _http_mock([], merchants_data)):
            _, aliases = _fetch_rules_and_aliases()

        assert len(aliases) == 2
        assert {a["merchantName"] for a in aliases} == {"Netflix", "MENY"}

    def test_merchant_with_no_aliases_contributes_nothing(self):
        merchants_data = [{"canonicalName": "Ghost", "defaultCategory": None, "aliases": []}]

        with patch("categorize.main.httpx.Client", _http_mock([], merchants_data)):
            _, aliases = _fetch_rules_and_aliases()

        assert aliases == []

    def test_cache_updated_after_fetch(self):
        rules_data = [{"name": "r1"}]
        merchants_data = [
            {"canonicalName": "Netflix", "defaultCategory": "Subscriptions",
             "aliases": [{"pattern": "NETFLIX", "matchType": "Contains"}]}
        ]

        with patch("categorize.main.httpx.Client", _http_mock(rules_data, merchants_data)):
            _fetch_rules_and_aliases()

        assert main_module._cached_rules == rules_data
        assert len(main_module._cached_aliases) == 1
        assert main_module._cache_expires_at > time.monotonic()

    def test_expired_cache_re_fetches(self):
        main_module._cached_rules = [{"old": True}]
        main_module._cache_expires_at = time.monotonic() - 1  # already expired

        with patch("categorize.main.httpx.Client", _http_mock([{"new": True}], [])):
            rules, _ = _fetch_rules_and_aliases()

        assert rules == [{"new": True}]

    def test_http_error_propagates(self):
        mock_client = MagicMock()
        mock_client.get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_cls = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(httpx.HTTPStatusError):
            with patch("categorize.main.httpx.Client", mock_cls):
                _fetch_rules_and_aliases()


# ── _enrich ───────────────────────────────────────────────────────────────────

_RULES = [{"name": "netflix-rule", "pattern": "NETFLIX", "matchType": "Contains",
           "category": "Subscriptions", "priority": 1}]
_ALIASES = [{"pattern": "MENY", "matchType": "StartsWith",
             "merchantName": "MENY", "defaultCategory": "Groceries"}]


class TestEnrich:
    def test_rule_match_sets_category(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=(_RULES, [])):
            enriched, attrs = _enrich({"raw_description": "NETFLIX MONTHLY"})

        assert enriched["category"] == "Subscriptions"
        assert attrs["categorize.matched_by"] == "rule"

    def test_rule_match_adds_rule_span_attributes(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=(_RULES, [])):
            _, attrs = _enrich({"raw_description": "NETFLIX MONTHLY"})

        assert attrs["categorize.rule.name"] == "netflix-rule"
        assert attrs["categorize.rule.priority"] == 1

    def test_merchant_default_used_when_no_rule_matches(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], _ALIASES)):
            enriched, attrs = _enrich({"raw_description": "MENY VESTERBRO"})

        assert enriched["category"] == "Groceries"
        assert attrs["categorize.matched_by"] == "merchant_default"

    def test_fallback_to_uncategorized_when_no_match(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], [])):
            enriched, attrs = _enrich({"raw_description": "UNKNOWN MERCHANT XYZ"})

        assert enriched["category"] == "Uncategorized"
        assert attrs["categorize.matched_by"] == "none"

    def test_rule_wins_over_merchant_default(self):
        rules = [{"name": "meny-rule", "pattern": "MENY", "matchType": "Contains",
                  "category": "Dining", "priority": 1}]
        aliases = [{"pattern": "MENY", "matchType": "Contains",
                    "merchantName": "MENY", "defaultCategory": "Groceries"}]

        with patch("categorize.main._fetch_rules_and_aliases", return_value=(rules, aliases)):
            enriched, attrs = _enrich({"raw_description": "MENY VESTERBRO"})

        assert enriched["category"] == "Dining"
        assert attrs["categorize.matched_by"] == "rule"

    def test_merchant_name_injected_when_resolved(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], _ALIASES)):
            enriched, attrs = _enrich({"raw_description": "MENY VESTERBRO"})

        assert enriched["merchant_name"] == "MENY"
        assert attrs["categorize.merchant.name"] == "MENY"

    def test_merchant_name_absent_when_no_merchant_match(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], [])):
            enriched, attrs = _enrich({"raw_description": "UNKNOWN"})

        assert "merchant_name" not in enriched
        assert "categorize.merchant.name" not in attrs

    def test_original_payload_keys_preserved(self):
        payload = {"raw_description": "MENY", "amount": 5000, "currency": "DKK", "account_id": "abc"}

        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], _ALIASES)):
            enriched, _ = _enrich(payload)

        assert enriched["amount"] == 5000
        assert enriched["currency"] == "DKK"
        assert enriched["account_id"] == "abc"

    def test_missing_raw_description_defaults_to_empty_string(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], [])):
            enriched, attrs = _enrich({"amount": 100})

        assert enriched["category"] == "Uncategorized"
        assert attrs["categorize.raw_description"] == ""

    def test_core_span_attributes_always_present(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], [])):
            _, attrs = _enrich({"raw_description": "X"})

        assert "categorize.raw_description" in attrs
        assert "categorize.category" in attrs
        assert "categorize.matched_by" in attrs

    def test_rule_span_attributes_absent_when_no_rule_match(self):
        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], [])):
            _, attrs = _enrich({"raw_description": "X"})

        assert "categorize.rule.name" not in attrs
        assert "categorize.rule.priority" not in attrs

    def test_merchant_with_null_default_category_falls_back_to_uncategorized(self):
        aliases = [{"pattern": "MENY", "matchType": "Contains",
                    "merchantName": "MENY", "defaultCategory": None}]

        with patch("categorize.main._fetch_rules_and_aliases", return_value=([], aliases)):
            enriched, attrs = _enrich({"raw_description": "MENY VESTERBRO"})

        assert enriched["category"] == "Uncategorized"
        assert attrs["categorize.matched_by"] == "none"
        assert enriched["merchant_name"] == "MENY"  # name resolved even without category
