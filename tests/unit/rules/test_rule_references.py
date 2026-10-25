"""The rules registry maps every implemented rule area to an official
source so coverage can be audited (M2 规则引用适配)."""

import pytest

from quant_agent.rules.references import (
    IMPLEMENTED_RULE_AREAS,
    RULE_REFERENCES,
    RuleReference,
)


def test_every_implemented_rule_area_has_a_reference():
    assert set(RULE_REFERENCES) == set(IMPLEMENTED_RULE_AREAS)


@pytest.mark.parametrize("area", sorted(IMPLEMENTED_RULE_AREAS))
def test_references_carry_source_title_and_issuer(area):
    reference = RULE_REFERENCES[area]

    assert isinstance(reference, RuleReference)
    assert reference.source_title.strip()
    assert reference.issuer in {"SSE", "SZSE", "SSE/SZSE"}
    # Honesty: unverified citations must say so instead of posing as checked.
    assert isinstance(reference.verified_online, bool)
    if not reference.verified_online:
        assert reference.note


def test_references_cover_price_limit_t1_lot_sessions_and_after_hours():
    for area in (
        "price_limits_main_board",
        "price_limits_star_chinext",
        "price_limits_new_listing",
        "t_plus_one",
        "lot_and_tick",
        "continuous_auction_sessions",
        "after_hours_fixed_price",
        "trading_calendar_holidays",
    ):
        assert area in RULE_REFERENCES
