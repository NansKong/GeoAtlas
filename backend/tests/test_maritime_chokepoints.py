"""Unit tests for Maritime Chokepoints Matching, Word-Boundary Enforcement,
Headline Deduplication, and Disrupted Status Guardrails.
"""

import re
import pytest
from workers.maritime_matcher import (
    MARITIME_CHOKEPOINTS,
    matches_chokepoint,
    deduplicate_headlines,
    evaluate_chokepoint_status,
)


@pytest.fixture
def chokepoint_regex_map():
    mapping = {}
    for cp in MARITIME_CHOKEPOINTS:
        mapping[cp["id"]] = [re.compile(p, re.IGNORECASE) for p in cp["location_terms"]]
    return mapping


# ─── 10 POSITIVE TEST CASES (MUST MATCH THE TARGET WATERWAY) ─────────────────
POSITIVE_CASES = [
    (
        "IRGC commandos seize foreign oil tanker in Strait of Hormuz",
        "hormuz",
    ),
    (
        "Houthi anti-ship ballistic missile strikes commercial container ship in Bab el-Mandeb",
        "bab-el-mandeb",
    ),
    (
        "Suez Canal maritime transit halted after ultra-large container ship runs aground",
        "suez",
    ),
    (
        "Armed pirates board bulk carrier underway in Strait of Malacca",
        "malacca",
    ),
    (
        "Turkey closes Bosporus to foreign navy warships under Montreux Convention rules",
        "bosporus",
    ),
    (
        "Panama Canal imposes strict draft restrictions reducing vessel transits",
        "panama",
    ),
    (
        "Gibraltar Port Authority detains oil tanker suspected of sanctions evasion",
        "gibraltar",
    ),
    (
        "Houthi explosive drone boat attacks commercial freighter in southern Red Sea",
        "bab-el-mandeb",
    ),
    (
        "Iranian naval gunboats harass British merchant vessel in Persian Gulf",
        "hormuz",
    ),
    (
        "Singapore Strait sees surge in nighttime armed robbery against container ships at anchor",
        "malacca",
    ),
]


@pytest.mark.parametrize("headline,expected_cp_id", POSITIVE_CASES)
def test_positive_maritime_matches(headline, expected_cp_id, chokepoint_regex_map):
    regexes = chokepoint_regex_map[expected_cp_id]
    assert matches_chokepoint(headline, regexes), (
        f"Expected headline to match chokepoint '{expected_cp_id}': {headline}"
    )


# ─── 10 NEGATIVE TEST CASES (MUST NOT MATCH FALSE SUBSTRINGS OR LAND EVENTS) ───
NEGATIVE_CASES = [
    # 1. Substring "ship" in "leadership"
    (
        "Leadership change announced in Iranian parliament following committee vote",
        "hormuz",
    ),
    # 2. Substring "mine" in "determine"
    (
        "UN Security Council convenes to determine international response to crisis",
        "bab-el-mandeb",
    ),
    # 3. Substring "transit" with "Panama" in land transport context
    (
        "Public transit bus collision disrupts traffic in central Panama City",
        "panama",
    ),
    # 4. "Red Sea" in non-maritime Egyptian tourism news
    (
        "Egyptian tourism flourishes at Red Sea beach resorts during winter season",
        "bab-el-mandeb",
    ),
    # 5. "Houthi" in land-based fighting in Yemen mountains (zero maritime terms)
    (
        "Houthi ground offensive clashes with Yemeni government forces in Marib mountains",
        "bab-el-mandeb",
    ),
    # 6. "Gibraltar" with non-maritime mining
    (
        "Gibraltar financial regulatory body approves new banking compliance guidelines",
        "gibraltar",
    ),
    # 7. Substring "ship" in "partnership" with "Malacca"
    (
        "Historic bilateral partnership agreement signed in downtown Malacca town",
        "malacca",
    ),
    # 8. "Bosporus" road suspension bridge traffic (zero naval/shipping terms)
    (
        "Turkish transport ministry raises toll rates on Bosporus road suspension bridge",
        "bosporus",
    ),
    # 9. Substring "relationship" with "Persian Gulf"
    (
        "Diplomatic relationship between Persian Gulf monarchies strengthens after summit",
        "hormuz",
    ),
    # 10. "Suez" governorate airport and air travel
    (
        "Domestic passenger flights in transit experience delays across Suez governorate",
        "suez",
    ),
]


@pytest.mark.parametrize("headline,cp_id", NEGATIVE_CASES)
def test_negative_maritime_non_matches(headline, cp_id, chokepoint_regex_map):
    regexes = chokepoint_regex_map[cp_id]
    assert not matches_chokepoint(headline, regexes), (
        f"False positive detected! Headline should NOT match '{cp_id}': {headline}"
    )


# ─── SYNDICATED HEADLINE DEDUPLICATION TESTS ──────────────────────────────────
def test_syndicated_wire_deduplication():
    """Verify that multiple wire outlets carrying the same story collapse to 1 cluster."""
    events = [
        {"id": "1", "title": "US Navy shoots down Houthi drone over Red Sea - Reuters"},
        {"id": "2", "title": "US Navy shoots down Houthi drone over Red Sea - AP News"},
        {"id": "3", "title": "US Navy shoots down Houthi drone over southern Red Sea - Bloomberg"},
        {"id": "4", "title": "US Navy intercepts Houthi attack drone in Red Sea - BBC News"},
    ]
    clusters = deduplicate_headlines(events)
    assert len(clusters) == 1, f"Expected 1 deduplicated story cluster, got {len(clusters)}"
    assert len(clusters[0]) == 4


def test_distinct_stories_separation():
    """Verify that genuinely different events are kept in separate clusters."""
    events = [
        {"id": "1", "title": "US Navy shoots down Houthi drone over Red Sea - Reuters"},
        {"id": "2", "title": "IRGC commandos seize foreign oil tanker in Strait of Hormuz - AP"},
        {"id": "3", "title": "Bulk carrier reports armed pirate boarding in Strait of Malacca"},
    ]
    clusters = deduplicate_headlines(events)
    assert len(clusters) == 3


# ─── STATUS THRESHOLD GUARDRAILS (NO SINGLE EVENT 'DISRUPTED') ─────────────────
def test_single_event_cannot_trigger_disrupted():
    """A single severe kinetic event (severity >= 4) must ONLY trigger 'elevated', NEVER 'disrupted'."""
    status = evaluate_chokepoint_status(distinct_story_count=1, has_severe_kinetic=True)
    assert status == "elevated", f"Expected 'elevated' for single severe event, got '{status}'"


def test_single_normal_event_is_normal():
    status = evaluate_chokepoint_status(distinct_story_count=1, has_severe_kinetic=False)
    assert status == "normal"


def test_two_distinct_stories_with_severe_impact_triggers_disrupted():
    """At least 2 distinct verified stories with severe kinetic impact triggers 'disrupted'."""
    status = evaluate_chokepoint_status(distinct_story_count=2, has_severe_kinetic=True)
    assert status == "disrupted"


def test_four_distinct_stories_triggers_disrupted():
    """4+ distinct stories in 7-day lookback triggers 'disrupted'."""
    status = evaluate_chokepoint_status(distinct_story_count=4, has_severe_kinetic=False)
    assert status == "disrupted"


def test_two_distinct_stories_without_severe_is_elevated():
    status = evaluate_chokepoint_status(distinct_story_count=2, has_severe_kinetic=False)
    assert status == "elevated"
