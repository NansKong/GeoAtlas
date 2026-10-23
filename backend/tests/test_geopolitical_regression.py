"""
Geopolitical & Macro Intelligence Regression Test Suite.

30 curated real-world headlines designed to guard against:
1. The pronoun "us" false-positive ("tell us", "let us", "between us").
2. Dateline bureau trap ("WASHINGTON (Reuters) - ...").
3. Demonyms & capital cities ("Kyiv", "Tehran", "Israeli", "Ukrainian").
4. News publisher name false matches ("- The Jerusalem Post").
5. European banking & sovereign yields ("Barclays", "French bond yields").
6. Actor vs. Location distinction ("US condemns airstrikes on Beirut").
7. Ambiguity handling ("Global" / "Unknown" when no clear winner).
"""

import re
from typing import Optional

# ── Legacy implementation from workers/event_pipeline.py ──
_LEGACY_COUNTRY_ALIASES: dict[str, str] = {
    "united states": "United States",
    "u.s.": "United States",
    "us": "United States",
    "china": "China",
    "india": "India",
    "russia": "Russia",
    "ukraine": "Ukraine",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "israel": "Israel",
    "iran": "Iran",
    "taiwan": "Taiwan",
    "japan": "Japan",
    "south korea": "South Korea",
    "north korea": "North Korea",
    "saudi arabia": "Saudi Arabia",
    "uae": "United Arab Emirates",
    "germany": "Germany",
    "france": "France",
}

_LEGACY_SHORT_TOKEN_ALIASES = {"us", "uk", "uae"}


def _legacy_extract_country(text: str) -> Optional[str]:
    """Exact replica of legacy _extract_country from workers/event_pipeline.py."""
    text_l = text.lower()
    for alias, canonical in _LEGACY_COUNTRY_ALIASES.items():
        if alias in _LEGACY_SHORT_TOKEN_ALIASES:
            if re.search(rf"\b{re.escape(alias)}\b", text_l):
                return canonical
        elif alias in text_l:
            return canonical
    return None



REGRESSION_HEADLINES = [
    # ── Category A: Pronoun "us" false-positives (Must NOT tag United States) ──
    {
        "id": "A1_oil_execs_tell_us",
        "title": "Oil executives tell us crude supplies will tighten sharply this winter",
        "body": "Energy analysts warn us that refinery margins could expand amid supply constraints.",
        "source": "Bloomberg",
        "expected_country": "Global",  # No country named, must not match "us"
    },
    {
        "id": "A2_let_us_examine_rates",
        "title": "Let us examine how Asian central banks respond to dollar strength",
        "body": "Economists join us to discuss currency interventions across Asian markets.",
        "source": "Reuters",
        "expected_country": "Global",
    },
    {
        "id": "A3_between_us_talks",
        "title": "Diplomats say talks between us and neighboring states concluded without deal",
        "body": "Officials urge us to remain patient as negotiations continue.",
        "source": "AP News",
        "expected_country": "Global",
    },

    # ── Category B: Demonyms & Capital Cities (Must tag the theater of event) ──
    {
        "id": "B1_kyiv_missiles",
        "title": "Russian missiles strike power substation in Kyiv amid subzero temperatures",
        "body": "Air raid sirens sounded across Kharkiv and Odesa as Ukrainian defense forces intercepted drones.",
        "source": "BBC News",
        "expected_country": "Ukraine",
    },
    {
        "id": "B2_tehran_retaliation",
        "title": "Tehran warns of decisive retaliation following strikes on military installations",
        "body": "Iranian officials stated IRGC naval units conducted exercises near the Strait of Hormuz.",
        "source": "Al Jazeera",
        "expected_country": "Iran",
    },
    {
        "id": "B3_tel_aviv_gaza",
        "title": "Rockets fired toward Tel Aviv as clashes intensify near northern border",
        "body": "Israeli defense systems intercepted multiple projectiles over central districts.",
        "source": "Reuters",
        "expected_country": "Israel",
    },
    {
        "id": "B4_beijing_tech_curbs",
        "title": "Beijing expands restrictions on rare earth exports to foreign semiconductor firms",
        "body": "Chinese commerce ministry officials cited national security interests.",
        "source": "Financial Times",
        "expected_country": "China",
    },
    {
        "id": "B5_tokyo_yen_intervention",
        "title": "Tokyo financial authorities signal readiness to support weakening yen",
        "body": "Bank of Japan governor commented on import price pressures in Japanese markets.",
        "source": "Nikkei",
        "expected_country": "Japan",
    },
    {
        "id": "B6_taipei_airspace",
        "title": "Fighter jets scramble from Taipei air base as foreign aircraft enter defense zone",
        "body": "Taiwanese defense ministry tracked maritime vessels across the strait.",
        "source": "Reuters",
        "expected_country": "Taiwan",
    },
    {
        "id": "B7_berlin_defence",
        "title": "Berlin approves export licenses for air defense systems to European partners",
        "body": "German defense ministry announced enhanced industrial cooperation across EU states.",
        "source": "DW",
        "expected_country": "Germany",
    },

    # ── Category C: Datelines & Bureau Traps (Must NOT tag bureau location) ──
    {
        "id": "C1_washington_dateline_kyiv",
        "title": "Heavy artillery battles intensify around Chasiv Yar",
        "body": "WASHINGTON (Reuters) - Pentagon officials reported heavy fighting in eastern Ukraine as Ukrainian brigades hold frontline positions.",
        "source": "Reuters",
        "expected_country": "Ukraine",  # Event is in Ukraine, despite WASHINGTON dateline
    },
    {
        "id": "C2_london_dateline_red_sea",
        "title": "Houthi anti-ship missile strikes commercial cargo vessel near Bab el-Mandeb",
        "body": "LONDON (Reuters) - Maritime insurance underwriters increased transit risk premiums for Red Sea shipping lanes.",
        "source": "Reuters",
        "expected_country": "Yemen",  # Or Global/Red Sea, NOT United Kingdom
    },
    {
        "id": "C3_new_york_dateline_paris",
        "title": "French bond yields surge as National Assembly faces no-confidence vote",
        "body": "NEW YORK (AP) - Wall Street investors dumped European sovereign debt following political instability in Paris.",
        "source": "AP News",
        "expected_country": "France",  # Event is in France, NOT United States
    },

    # ── Category D: Publisher Suffix & Outlet Name Traps ──
    {
        "id": "D1_jerusalem_post_suffix",
        "title": "IDF expands northern defensive perimeter - The Jerusalem Post",
        "body": "Military leadership announced increased troop deployments along border sectors.",
        "source": "The Jerusalem Post",
        "expected_country": "Israel",  # Valid Israel story, but title cleaning must strip suffix
    },
    {
        "id": "D2_jerusalem_post_foreign_story",
        "title": "Sudanese armed forces clash with paramilitary group in Khartoum - The Jerusalem Post",
        "body": "Heavy civilian displacement reported across central Sudan as peace talks stall.",
        "source": "The Jerusalem Post",
        "expected_country": "Sudan",  # Must NOT tag Israel just because source is Jerusalem Post!
    },
    {
        "id": "D3_reuters_suffix_barclays",
        "title": "Barclays cuts European sovereign debt exposure amid French political gridlock - Reuters",
        "body": "British lender reduced holdings as French spread widening accelerated across eurozone desks.",
        "source": "Reuters",
        "expected_country": "France",  # Or United Kingdom, but definitely NOT United States
    },

    # ── Category E: Actor vs. Location Distinction ──
    {
        "id": "E1_us_condemns_beirut",
        "title": "US condemns heavy airstrikes targeting southern suburbs of Beirut",
        "body": "State Department spokespersons urged de-escalation as Lebanese authorities reported casualties.",
        "source": "BBC News",
        "expected_country": "Lebanon",  # Target/theater is Lebanon, Actor is US
    },
    {
        "id": "E2_us_imposes_sanctions_moscow",
        "title": "US Treasury blacklists shipping network transporting Russian crude above price cap",
        "body": "New sanctions target maritime facilitators evasion networks across the Persian Gulf.",
        "source": "Bloomberg",
        "expected_country": "Russia",  # Target of sanctions is Russia
    },
    {
        "id": "E3_france_deploys_red_sea",
        "title": "French frigate intercepts attack drones threatening international navigation off Yemeni coast",
        "body": "Paris armed forces ministry confirmed naval engagement in international waters.",
        "source": "AFP",
        "expected_country": "Yemen",  # Location of attack is off Yemen
    },
    {
        "id": "E4_washington_warns_tehran",
        "title": "Washington warns Tehran against maritime interdictions through Strait of Hormuz",
        "body": "White House national security officials cautioned Iranian naval commanders against disruptions to energy transit.",
        "source": "Reuters",
        "expected_country": "Iran",  # Target/theater of warning is Iran, Actor is US
    },

    # ── Category F: Legitimate United States Events ──
    {
        "id": "F1_fed_cuts_rates",
        "title": "Federal Reserve lowers benchmark interest rate by 25 basis points in Washington",
        "body": "US central bank policymakers cited cooling domestic inflation and labor market moderation.",
        "source": "Wall Street Journal",
        "expected_country": "United States",
    },
    {
        "id": "F2_us_dockworkers_strike",
        "title": "East Coast dockworkers strike halts container operations across major American ports",
        "body": "Union representatives from Maine to Texas shut down shipping terminals demanding wage increases.",
        "source": "Reuters",
        "expected_country": "United States",
    },
    {
        "id": "F3_us_supreme_court",
        "title": "US Supreme Court agrees to hear challenge on federal environmental regulatory authority",
        "body": "Justices scheduled oral arguments for upcoming term affecting domestic power generation.",
        "source": "AP News",
        "expected_country": "United States",
    },

    # ── Category G: European & Global Macro Events ──
    {
        "id": "G1_ecb_frankfurt",
        "title": "ECB cuts deposit facility rate at Frankfurt policy meeting as German factory output contracts",
        "body": "European Central Bank cited disinflation trends across core eurozone economies.",
        "source": "Financial Times",
        "expected_country": "Germany",  # Or European Union
    },
    {
        "id": "G2_uk_autumn_budget",
        "title": "Chancellor Rachel Reeves unveils UK Autumn Budget with tax hikes and infrastructure borrowing",
        "body": "HM Treasury announced fiscal measures in Westminster to stabilize British public services.",
        "source": "BBC News",
        "expected_country": "United Kingdom",
    },
    {
        "id": "G3_opec_vienna",
        "title": "OPEC+ delegates in Vienna agree to postpone planned oil production increases",
        "body": "Saudi Arabia and allied petroleum producers cited sluggish global demand forecasts.",
        "source": "Reuters",
        "expected_country": "Saudi Arabia",
    },

    # ── Category H: Ambiguous / Multi-Country Stories (Must NOT guess US) ──
    {
        "id": "H1_global_shipping_rates",
        "title": "Container freight rates drop 12% worldwide as new vessel deliveries ease capacity",
        "body": "Global maritime indexes show balanced supply across transpacific and European trade lanes.",
        "source": "Freightos",
        "expected_country": "Global",
    },
    {
        "id": "H2_crypto_liquidation",
        "title": "Crypto liquidations exceed $400 million following sharp intraday volatility",
        "body": "Derivatives exchanges recorded long liquidations across digital asset markets.",
        "source": "CoinDesk",
        "expected_country": "Global",
    },
    {
        "id": "H3_ai_chip_demand",
        "title": "Hyperscale cloud providers expand capital expenditure on artificial intelligence accelerators",
        "body": "Leading technology infrastructure firms report accelerated datacentre procurement cycles.",
        "source": "TechCrunch",
        "expected_country": "Global",
    },
    {
        "id": "H4_semiconductor_supply_chain",
        "title": "Advanced packaging capacity constraints delay next-generation processor deliveries",
        "body": "Foundries and equipment makers report lead times exceeding 30 weeks.",
        "source": "EE Times",
        "expected_country": "Global",
    },
]


def test_baseline_legacy_extractor_accuracy():
    """
    Measure baseline failure rate of the legacy _extract_country implementation.
    Documents the exact bugs (pronoun 'us', datelines, demonyms).
    """
    passed = 0
    failures = []

    for item in REGRESSION_HEADLINES:
        text = f"{item['title']}\n{item['body']}"
        actual = _legacy_extract_country(text)
        expected = item["expected_country"]

        # Accept either exact match, or 'Global' when no specific country, or accepted variants
        is_match = False
        if expected == "Global" and actual is None:
            is_match = True
        elif actual == expected:
            is_match = True
        elif expected in ("France", "United Kingdom") and actual in ("France", "United Kingdom"):
            # Barclays story has UK bank + French bonds
            is_match = True
        elif expected in ("Israel", "Lebanon") and actual in ("Israel", "Lebanon"):
            is_match = True

        if is_match:
            passed += 1
        else:
            failures.append({
                "id": item["id"],
                "title": item["title"][:50],
                "expected": expected,
                "legacy_got": actual,
            })

    total = len(REGRESSION_HEADLINES)
    accuracy = (passed / total) * 100.0
    print(f"\n[LEGACY BASELINE ACCURACY]: {passed}/{total} ({accuracy:.1f}%)")
    for f in failures:
        print(f"  FAILED {f['id']}: expected '{f['expected']}', got '{f['legacy_got']}' (Title: {f['title']})")

    assert total == 30


def test_new_geo_tagger_accuracy():
    """
    Test the new high-precision extract_countries against the exact same 30 regression headlines.
    Demonstrates the fix of pronoun 'us', demonyms, cities, datelines, and publisher suffixes.
    """
    from workers.geo_tagger import extract_countries

    passed = 0
    failures = []

    for item in REGRESSION_HEADLINES:
        primary, secondary = extract_countries(
            title=item["title"],
            body=item["body"],
            source=item["source"],
        )
        expected = item["expected_country"]

        is_match = False
        if expected == "Global" and (primary == "Global" or primary is None):
            is_match = True
        elif primary == expected:
            is_match = True
        elif expected in ("France", "United Kingdom") and primary in ("France", "United Kingdom"):
            is_match = True
        elif expected in ("Israel", "Lebanon") and primary in ("Israel", "Lebanon"):
            is_match = True
        elif expected in ("Yemen", "Global") and primary in ("Yemen", "Global"):
            is_match = True

        if is_match:
            passed += 1
        else:
            failures.append({
                "id": item["id"],
                "title": item["title"][:50],
                "expected": expected,
                "new_got": primary,
                "secondary": secondary,
            })

    total = len(REGRESSION_HEADLINES)
    accuracy = (passed / total) * 100.0
    print(f"\n[NEW GEO-TAGGER ACCURACY]: {passed}/{total} ({accuracy:.1f}%)")
    for f in failures:
        print(f"  FAILED {f['id']}: expected '{f['expected']}', got '{f['new_got']}' (Secondary: {f['secondary']}, Title: {f['title']})")

    # Assert dramatic improvement over legacy 14/30 (46.7%)
    assert accuracy >= 90.0, f"Expected >= 90% accuracy, got {accuracy:.1f}% ({passed}/{total})"

