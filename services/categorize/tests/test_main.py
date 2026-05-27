import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from categorize.main import _matches, _apply_rules, _resolve_merchant


# ── _matches ──────────────────────────────────────────────────────────────────

class TestMatches:
    def test_contains_match(self):
        assert _matches("SPOTIFY PREMIUM", "spotify", "Contains")

    def test_contains_case_insensitive(self):
        assert _matches("Spotify Premium", "SPOTIFY", "Contains")

    def test_contains_no_match(self):
        assert not _matches("NETFLIX", "spotify", "Contains")

    def test_exact_match(self):
        assert _matches("SPOTIFY", "spotify", "Exact")

    def test_exact_no_match(self):
        assert not _matches("SPOTIFY PREMIUM", "spotify", "Exact")

    def test_startswith_match(self):
        assert _matches("MENY VESTERBRO", "MENY", "StartsWith")

    def test_startswith_no_match(self):
        assert not _matches("NETTO VESTERBRO", "MENY", "StartsWith")

    def test_regex_match(self):
        assert _matches("MOBILEPAY*12345", r"MOBILEPAY\*\d+", "Regex")

    def test_regex_no_match(self):
        assert not _matches("SPOTIFY", r"MOBILEPAY\*\d+", "Regex")

    def test_unknown_match_type_returns_false(self):
        assert not _matches("anything", "anything", "Unknown")


# ── _apply_rules ──────────────────────────────────────────────────────────────

class TestApplyRules:
    def _rule(self, pattern, match_type, category, priority):
        return {"pattern": pattern, "matchType": match_type, "category": category, "priority": priority}

    def test_returns_none_for_no_rules(self):
        assert _apply_rules("SPOTIFY", []) is None

    def test_applies_matching_rule(self):
        rules = [self._rule("SPOTIFY", "Contains", "Subscriptions", 1)]
        result = _apply_rules("SPOTIFY PREMIUM", rules)
        assert result is not None
        assert result["category"] == "Subscriptions"

    def test_lower_priority_wins(self):
        rules = [
            self._rule("SPOTIFY", "Contains", "Subscriptions", 10),
            self._rule("SPOTIFY", "Contains", "Entertainment", 1),
        ]
        assert _apply_rules("SPOTIFY PREMIUM", rules)["category"] == "Entertainment"

    def test_no_matching_rule_returns_none(self):
        rules = [self._rule("NETFLIX", "Contains", "Subscriptions", 1)]
        assert _apply_rules("SPOTIFY", rules) is None

    def test_first_matching_rule_by_priority_wins(self):
        rules = [
            self._rule("MENY", "Contains", "Groceries", 2),
            self._rule("MENY VESTERBRO", "Exact", "Dining", 1),
        ]
        assert _apply_rules("MENY VESTERBRO", rules)["category"] == "Dining"

    def test_returns_full_rule_dict(self):
        rules = [self._rule("SPOTIFY", "Contains", "Subscriptions", 5)]
        result = _apply_rules("SPOTIFY PREMIUM", rules)
        assert result["pattern"] == "SPOTIFY"
        assert result["priority"] == 5


# ── _resolve_merchant ─────────────────────────────────────────────────────────

class TestResolveMerchant:
    def _alias(self, pattern, match_type, merchant_name, default_category=None):
        return {
            "pattern": pattern,
            "matchType": match_type,
            "merchantName": merchant_name,
            "defaultCategory": default_category,
        }

    def test_returns_none_when_no_aliases(self):
        assert _resolve_merchant("MENY VESTERBRO", []) is None

    def test_resolves_matching_alias(self):
        aliases = [self._alias("MENY", "Contains", "MENY")]
        result = _resolve_merchant("MENY VESTERBRO", aliases)
        assert result is not None
        assert result["merchantName"] == "MENY"

    def test_returns_none_when_no_alias_matches(self):
        aliases = [self._alias("NETTO", "Contains", "NETTO")]
        assert _resolve_merchant("MENY VESTERBRO", aliases) is None

    def test_includes_default_category(self):
        aliases = [self._alias("MobilePay", "Contains", "MobilePay", "Transfer")]
        result = _resolve_merchant("MobilePay*12345 Rune", aliases)
        assert result is not None
        assert result["merchantName"] == "MobilePay"
        assert result["defaultCategory"] == "Transfer"

    def test_default_category_can_be_none(self):
        aliases = [self._alias("MENY", "StartsWith", "MENY", None)]
        result = _resolve_merchant("MENY ØSTERBRO", aliases)
        assert result is not None
        assert result["defaultCategory"] is None
