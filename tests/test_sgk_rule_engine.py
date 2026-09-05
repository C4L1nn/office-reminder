from datetime import date

from services.sgk_rule_engine import SgkRuleEngine


def test_following_month_end() -> None:
    assert SgkRuleEngine.following_month_end(2026, 8) == date(2026, 9, 30)
    assert SgkRuleEngine.following_month_end(2026, 12) == date(2027, 1, 31)


def test_weekend_moves_forward() -> None:
    assert SgkRuleEngine.move_weekend_to_next_weekday(date(2026, 5, 31)) == date(2026, 6, 1)
