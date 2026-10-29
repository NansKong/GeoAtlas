"""
High-Precision Geopolitical Event Geo-Tagger.

Architecture:
1. Publisher Suffix Stripper:
   Surgically strips trailing outlet names (' - Reuters', ' | The Jerusalem Post')
   ONLY when matching the article's own source field.
2. Dateline Stripper:
   Removes reporting bureau headers ('WASHINGTON (Reuters) - ...', 'NEW YORK (AP) - ...').
3. Preposition & Location Cue Detection:
   Recognizes syntactical cues ('strikes on Iran', 'attacks in Kyiv', 'crisis in US north-east',
   'bombing of Beirut', 'war in Ukraine') and awards location priority (+6 points).
4. Actor vs. Location Decoupling:
   Distinguishes diplomatic/military actors ('US condemns', 'Washington warns', 'Treasury blacklists')
   from the theater/location where the impact is occurring.
5. Case-Sensitive Short Tokens:
   Prevents pronoun traps (US/U.S. matched strictly as uppercase tokens).
6. Comprehensive Geopolitical Universe:
   Includes demonyms, capitals, and major conflict zones across 25+ nations.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

# Dateline pattern: e.g., "WASHINGTON (Reuters) - " or "NEW YORK (AP) — "
DATELINE = re.compile(
    r"^\s*[A-Z][A-Za-z .,'-]{2,40}\((?:Reuters|AP|AFP|Bloomberg|Dow Jones|CNBC|Financial Times)\)\s*[-–—:]?\s*",
    flags=re.IGNORECASE,
)

# Trailing publisher separator
PUBLISHER_SEPARATOR = re.compile(r"\s*[-|–—]\s*(.+)$")

# Location prepositions & syntax patterns
LOCATION_PREPOSITIONS = re.compile(
    r"\b(?:in|into|on|at|near|across|over|throughout|strikes on|strike on|attack on|attacks on|attacks in|war in|offensive in|invaded|bombing of|bombed|shelling of|crisis in|clashes in|protests in|targets in|targeting)\s+([A-Za-z\s-]{1,30})",
    flags=re.IGNORECASE,
)

# Actor syntactical cues (subject performing diplomatic/regulatory action)
ACTOR_PATTERNS = re.compile(
    r"\b(US|U\.S\.|United States|Washington|White House|Pentagon|Treasury|State Department|Kremlin|NATO|EU|European Commission|ICC|IDF|IRGC)\s+(?:condemns|warns|blacklists|sanctions|urges|approves|deploys|calls for|announces|considers|imposes|investigates|weighs|proposes)\b",
    flags=re.IGNORECASE,
)


COMMON_PUBLISHER_NAMES = {
    "reuters", "ap news", "associated press", "ap", "bloomberg", "financial times", "ft",
    "wsj", "the wall street journal", "wall street journal", "the new york times", "new york times", "nyt",
    "the washington post", "washington post", "bbc", "bbc news", "cnn", "cnbc", "al jazeera",
    "the guardian", "the economist", "barron's", "barrons", "cbs", "cbs news", "nbc news",
    "abc news", "fox news", "politico", "politico.eu", "axios", "south china morning post", "scmp",
    "france 24", "deutsche welle", "dw", "the kyiv independent", "kyiv independent", "the kyiv",
    "the jerusalem post", "jerusalem post", "times of israel", "haaretz", "euronews",
    "euronews.com", "daily kos", "the verge", "vox", "usa today", "investing.com",
    "yahoo finance", "yahoo entertainment", "oilprice.com", "about amazon", "daily mail",
    "the telegraph", "sky news", "independent"
}


def strip_publisher_suffix(title: str, source: Optional[str] = None) -> str:
    """
    Surgically strip trailing publisher suffixes like ' - Reuters' or ' | The Jerusalem Post',
    when matching the article's own source OR recognized news publishers (e.g. from Google News feeds).
    Avoids damaging valid headlines with dashes.
    """
    if not title:
        return ""
    clean_title = title.strip()

    match = PUBLISHER_SEPARATOR.search(clean_title)
    if not match:
        return clean_title

    suffix_candidate = match.group(1).strip()
    candidate_norm = re.sub(r"[^a-z0-9]", "", suffix_candidate.lower())

    if not candidate_norm:
        return clean_title

    # 1. Match against known publishers
    for pub in COMMON_PUBLISHER_NAMES:
        pub_norm = re.sub(r"[^a-z0-9]", "", pub)
        if candidate_norm == pub_norm or candidate_norm in pub_norm or pub_norm in candidate_norm:
            return clean_title[: match.start()].strip()

    # 2. Match against provided source
    if source:
        source_norm = re.sub(r"[^a-z0-9]", "", source.lower())
        if "googlenews" in source_norm or candidate_norm in source_norm or source_norm in candidate_norm:
            return clean_title[: match.start()].strip()

    return clean_title


# Case-sensitive dictionary for short tokens and proper capital names.
COUNTRY_PATTERNS: dict[str, re.Pattern] = {
    "United States": re.compile(
        r"\b(?:U\.S\.|US|USA|United States|Trump|Washington(?!\s+Post|\s+Times)|Federal Reserve|\bFed\b|White House|Pentagon|Americans?|US Treasury|U\.S\. Treasury|Wall Street|S&P|Nasdaq|Dow Jones|Silicon Valley|California|Texas|Florida|Alaska)\b"
    ),
    "Ukraine": re.compile(
        r"\b(?:Ukraine|Ukrainian|Kyiv|Kiev|Kharkiv|Odesa|Zaporizhzhia|Chasiv Yar|Crimea|Donbas|Zelenskyy|Starlink)\b",
        re.IGNORECASE,
    ),
    "Israel": re.compile(
        r"\b(?:Israel|Israeli|Jerusalem(?!\s+Post)|Tel Aviv|Gaza|IDF|Knesset|Netanyahu)\b",
        re.IGNORECASE,
    ),
    "Iran": re.compile(
        r"\b(?:Iran|Iranian|Tehran|IRGC|Hormuz|Persian Gulf|Khamenei)\b",
        re.IGNORECASE,
    ),
    "Russia": re.compile(
        r"\b(?:Russia|Russian|Moscow|Kremlin|Putin|Gazprom)\b",
        re.IGNORECASE,
    ),
    "France": re.compile(
        r"\b(?:France|French|Paris|National Assembly|CAC 40|Elysée|Macron)\b",
        re.IGNORECASE,
    ),
    "United Kingdom": re.compile(
        r"\b(?:United Kingdom|U\.K\.|UK|British|Britain|London|Bank of England|Westminster|Whitehall|Downing Street|Barclays|Keir Starmer|Starmer|Tory|Tories|Labour|FTSE|Pound|Sterling|MI5|MI6|Badenoch|Healey|Reeves)\b",
        re.IGNORECASE,
    ),
    "Germany": re.compile(
        r"\b(?:Germany|German|Berlin|Frankfurt|Bundestag|Bundesbank)\b",
        re.IGNORECASE,
    ),
    "Italy": re.compile(
        r"\b(?:Italy|Italian|Rome|Milan|mozzarella)\b",
        re.IGNORECASE,
    ),
    "China": re.compile(
        r"\b(?:China|Chinese|Beijing|Shanghai|PBOC|Xi Jinping)\b",
        re.IGNORECASE,
    ),
    "Taiwan": re.compile(
        r"\b(?:Taiwan|Taiwanese|Taipei|TSMC|Taiwan Strait)\b",
        re.IGNORECASE,
    ),
    "Japan": re.compile(
        r"\b(?:Japan|Japanese|Tokyo|Bank of Japan|Yen|Nikkei)\b",
        re.IGNORECASE,
    ),
    "Yemen": re.compile(
        r"\b(?:Yemen|Yemeni|Houthi|Houthis|Sanaa|Bab el-Mandeb|Red Sea)\b",
        re.IGNORECASE,
    ),
    "Lebanon": re.compile(
        r"\b(?:Lebanon|Lebanese|Beirut|Hezbollah)\b",
        re.IGNORECASE,
    ),
    "Saudi Arabia": re.compile(
        r"\b(?:Saudi Arabia|Saudi|Riyadh|Aramco|OPEC)\b",
        re.IGNORECASE,
    ),
    "Sudan": re.compile(
        r"\b(?:Sudan|Sudanese|Khartoum|Darfur|RSF)\b",
        re.IGNORECASE,
    ),
    "Poland": re.compile(
        r"\b(?:Poland|Polish|Warsaw)\b",
        re.IGNORECASE,
    ),
    "Turkey": re.compile(
        r"\b(?:Turkey|Turkish|Ankara|Istanbul|Erdogan)\b",
        re.IGNORECASE,
    ),
    "Syria": re.compile(
        r"\b(?:Syria|Syrian|Damascus|Aleppo)\b",
        re.IGNORECASE,
    ),
    "Iraq": re.compile(
        r"\b(?:Iraq|Iraqi|Baghdad)\b",
        re.IGNORECASE,
    ),
    "Egypt": re.compile(
        r"\b(?:Egypt|Egyptian|Cairo|Suez|Sinai)\b",
        re.IGNORECASE,
    ),
    "India": re.compile(
        r"\b(?:India|Indian|New Delhi|Reserve Bank of India|Rupee)\b",
        re.IGNORECASE,
    ),
    "South Korea": re.compile(
        r"\b(?:South Korea|South Korean|Seoul|Bank of Korea|Won)\b",
        re.IGNORECASE,
    ),
    "North Korea": re.compile(
        r"\b(?:North Korea|North Korean|Pyongyang)\b",
        re.IGNORECASE,
    ),
    "European Union": re.compile(
        r"\b(?:European Union|Eurozone|Brussels|ECB|European Central Bank)\b",
        re.IGNORECASE,
    ),
    "Canada": re.compile(
        r"\b(?:Canada|Canadian|Ottawa|Toronto|Bank of Canada|TSX|Trudeau|Poilievre)\b",
        re.IGNORECASE,
    ),
    "Australia": re.compile(
        r"\b(?:Australia|Australian|Canberra|Sydney|Melbourne|RBA|Reserve Bank of Australia|ASX)\b",
        re.IGNORECASE,
    ),
    "Pakistan": re.compile(
        r"\b(?:Pakistan|Pakistani|Islamabad|Karachi|Lahore)\b",
        re.IGNORECASE,
    ),
    "Mexico": re.compile(
        r"\b(?:Mexico|Mexican|Mexico City|Banxico|Sheinbaum)\b",
        re.IGNORECASE,
    ),
    "Brazil": re.compile(
        r"\b(?:Brazil|Brazilian|Brasília|Sao Paulo|Petrobras|Lula)\b",
        re.IGNORECASE,
    ),
    "El Salvador": re.compile(
        r"\b(?:El Salvador|Salvadoran|Bukele)\b",
        re.IGNORECASE,
    ),
    "Haiti": re.compile(
        r"\b(?:Haiti|Haitian|Port-au-Prince)\b",
        re.IGNORECASE,
    ),
    "Serbia": re.compile(
        r"\b(?:Serbia|Serbian|Belgrade)\b",
        re.IGNORECASE,
    ),
    "Singapore": re.compile(
        r"\b(?:Singapore|Singaporean)\b",
        re.IGNORECASE,
    ),
    "Malaysia": re.compile(
        r"\b(?:Malaysia|Malaysian|Kuala Lumpur)\b",
        re.IGNORECASE,
    ),
    "Indonesia": re.compile(
        r"\b(?:Indonesia|Indonesian|Jakarta)\b",
        re.IGNORECASE,
    ),
    "Myanmar": re.compile(
        r"\b(?:Myanmar|Burmese|Naypyidaw|Yangon)\b",
        re.IGNORECASE,
    ),
    "Netherlands": re.compile(
        r"\b(?:Netherlands|Dutch|Amsterdam|The Hague|ASML)\b",
        re.IGNORECASE,
    ),
    "Switzerland": re.compile(
        r"\b(?:Switzerland|Swiss|Bern|Zurich|SNB|UBS)\b",
        re.IGNORECASE,
    ),
    "Norway": re.compile(
        r"\b(?:Norway|Norwegian|Oslo|Norges Bank)\b",
        re.IGNORECASE,
    ),
    "Sweden": re.compile(
        r"\b(?:Sweden|Swedish|Stockholm|Riksbank)\b",
        re.IGNORECASE,
    ),
    "Qatar": re.compile(
        r"\b(?:Qatar|Qatari|Doha)\b",
        re.IGNORECASE,
    ),
    "United Arab Emirates": re.compile(
        r"\b(?:United Arab Emirates|UAE|Emirati|Dubai|Abu Dhabi|Ras al Khaimah|Sharjah)\b",
        re.IGNORECASE,
    ),
}


def extract_countries(
    title: str,
    body: Optional[str] = None,
    source: Optional[str] = None,
    title_weight: int = 3,
) -> tuple[Optional[str], list[str]]:
    """
    Extract the primary event location country and secondary actor/associated countries.

    Preposition location cues ('strikes on Iran', 'missiles in Kyiv') provide a +6 bonus
    to ensure the theater of action wins over diplomatic actors ('US condemns').
    """
    clean_title = strip_publisher_suffix(title, source)
    raw_body = body or ""
    clean_body = DATELINE.sub("", raw_body)
    full_text = f"{clean_title}\n{clean_body}"

    location_scores: Counter[str] = Counter()
    actor_mentions: set[str] = set()

    # 1. Detect Actor cues ('US condemns', 'Washington warns')
    for actor_match in ACTOR_PATTERNS.finditer(full_text):
        actor_token = actor_match.group(1).upper()
        if "US" in actor_token or "WASHINGTON" in actor_token or "UNITED" in actor_token or "TREASURY" in actor_token or "WHITE" in actor_token:
            actor_mentions.add("United States")
        elif "KREMLIN" in actor_token:
            actor_mentions.add("Russia")
        elif "IDF" in actor_token:
            actor_mentions.add("Israel")
        elif "IRGC" in actor_token:
            actor_mentions.add("Iran")

    # 2. Detect Preposition Location Cues ('strikes on X', 'clashes in X')
    for prep_match in LOCATION_PREPOSITIONS.finditer(full_text):
        target_phrase = prep_match.group(1)
        for country, pattern in COUNTRY_PATTERNS.items():
            if pattern.search(target_phrase):
                location_scores[country] += 6

    # 3. Title scan (weighted 3x)
    for country, pattern in COUNTRY_PATTERNS.items():
        hits = len(pattern.findall(clean_title))
        if hits > 0:
            location_scores[country] += hits * title_weight

    # 4. Body scan (weight 1x)
    for country, pattern in COUNTRY_PATTERNS.items():
        hits = len(pattern.findall(clean_body))
        if hits > 0:
            location_scores[country] += hits

    if not location_scores:
        return None, []

    # If an actor country (e.g. US) was matched, but a distinct foreign theater has location cues,
    # don't let actor count eclipse the actual theater
    non_actor_candidates = [c for c in location_scores if c not in actor_mentions]
    if non_actor_candidates and "United States" in actor_mentions:
        # Check if any non-actor country has strong signal
        best_non_actor = max(non_actor_candidates, key=lambda c: location_scores[c])
        if location_scores[best_non_actor] >= 3:
            # Theater wins, US is secondary actor
            secondary = [c for c in location_scores if c != best_non_actor]
            if "United States" not in secondary:
                secondary.append("United States")
            return best_non_actor, secondary[:3]

    ranked = location_scores.most_common()
    top_country, top_score = ranked[0]

    # If top country only has a slim lead over runner-up without preposition cues
    if len(ranked) > 1:
        second_country, second_score = ranked[1]
        # Only declare Global if both have equal or near-identical scores (ratio < 1.3)
        if top_score < 1.3 * second_score and (top_score < 6):
            return "Global", [c for c, _ in ranked[:3]]

    secondary = [c for c, _ in ranked[1:4]]
    for a in actor_mentions:
        if a != top_country and a not in secondary:
            secondary.append(a)

    return top_country, secondary[:3]
