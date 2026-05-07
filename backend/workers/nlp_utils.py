from __future__ import annotations

import re
from typing import Optional

from core.config import settings
from workers.model_runtime import predict_relevance, predict_sentiment

try:
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    DetectorFactory.seed = 0
except Exception:  # pragma: no cover - optional runtime dependency
    DetectorFactory = None
    LangDetectException = Exception
    detect_langs = None


RELEVANCE_SIGNAL_GROUPS: dict[str, tuple[str, ...]] = {
    "geopolitics": (
        "geopolitics",
        "geopolitical",
        "sanction",
        "embargo",
        "tariff",
        "trade restriction",
        "export control",
        "military",
        "conflict",
        "war",
        "missile",
        "election",
        "ballot",
        "policy",
        "regulation",
        "antitrust",
    ),
    "macro": (
        "inflation",
        "cpi",
        "gdp",
        "interest rate",
        "rate cut",
        "rate hike",
        "central bank",
        "unemployment",
        "retail sales",
        "manufacturing",
        "pmi",
        "treasury",
        "yield",
    ),
    "energy_supply": (
        "oil",
        "crude",
        "gas",
        "lng",
        "pipeline",
        "refinery",
        "opec",
        "power outage",
        "energy disruption",
        "shipping route",
        "strait of hormuz",
    ),
    "markets": (
        "market",
        "stocks",
        "shares",
        "equity",
        "investor",
        "earnings",
        "guidance",
        "volatility",
        "sector",
        "semiconductor",
        "chip",
        "currency",
        "forex",
        "commodity",
    ),
}

IRRELEVANT_SIGNAL_TERMS = (
    "sports",
    "football",
    "soccer",
    "cricket",
    "nba",
    "nfl",
    "movie",
    "box office",
    "celebrity",
    "fashion",
    "lifestyle",
    "recipe",
    "travel tips",
    "horoscope",
    "weather forecast",
)

ENGLISH_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "will",
    "have",
    "after",
    "into",
    "about",
}


def _normalize_text(text: Optional[str]) -> str:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    return normalized[:5000]


def detect_article_language(text: Optional[str]) -> tuple[str, float]:
    normalized = _normalize_text(text)
    if not normalized:
        return "unknown", 0.0

    if detect_langs is not None:
        try:
            results = detect_langs(normalized)
            if results:
                best = results[0]
                return best.lang.lower(), float(best.prob)
        except LangDetectException:
            pass

    alpha_tokens = re.findall(r"[A-Za-z]+", normalized.lower())
    if not alpha_tokens:
        return "unknown", 0.0

    stopword_hits = sum(1 for token in alpha_tokens if token in ENGLISH_STOPWORDS)
    ascii_chars = sum(1 for ch in normalized if ord(ch) < 128)
    ascii_ratio = ascii_chars / max(1, len(normalized))
    confidence = min(0.92, 0.52 + (stopword_hits / max(1, len(alpha_tokens))) * 1.6 + ascii_ratio * 0.18)
    if ascii_ratio >= 0.95 and len(alpha_tokens) >= 3:
        confidence = max(confidence, 0.82)
    return "en", confidence


def score_article_relevance(text: Optional[str], source: Optional[str] = None) -> float:
    raw_normalized = _normalize_text(text)
    normalized = raw_normalized.lower()
    if not normalized:
        return 0.0

    model_score, _ = predict_relevance(raw_normalized)
    if model_score is not None:
        return max(0.0, min(1.0, model_score))

    score = 0.16
    for weight, keywords in (
        (0.18, RELEVANCE_SIGNAL_GROUPS["geopolitics"]),
        (0.14, RELEVANCE_SIGNAL_GROUPS["macro"]),
        (0.12, RELEVANCE_SIGNAL_GROUPS["energy_supply"]),
        (0.08, RELEVANCE_SIGNAL_GROUPS["markets"]),
    ):
        hits = sum(1 for keyword in keywords if keyword in normalized)
        score += min(weight, hits * (weight / 2))

    if re.search(r"\b[A-Z]{2,5}\b", raw_normalized):
        score += 0.05

    source_l = (source or "").lower()
    if any(token in source_l for token in ("reuters", "ap", "associated press", "bloomberg", "wsj", "ft")):
        score += 0.05

    negative_hits = sum(1 for keyword in IRRELEVANT_SIGNAL_TERMS if keyword in normalized)
    if negative_hits:
        score -= min(0.30, 0.10 * negative_hits)

    if len(normalized) < 80:
        score -= 0.06

    return max(0.0, min(1.0, score))


def relevance_label_for_score(score: float) -> str:
    return "relevant" if score >= settings.NLP_RELEVANCE_THRESHOLD else "irrelevant"


def article_passes_language_gate(language_code: str, confidence: float) -> bool:
    allowed_languages = {
        token.strip().lower()
        for token in settings.NLP_ALLOWED_LANGUAGES.split(",")
        if token.strip()
    }
    if not allowed_languages:
        return True
    if language_code not in allowed_languages:
        return False
    return confidence >= settings.NLP_MIN_LANGUAGE_CONFIDENCE


def compute_article_sentiment(text: Optional[str]) -> Optional[float]:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    model_score = predict_sentiment(normalized)
    if model_score is not None:
        return max(-1.0, min(1.0, model_score))

    lowered = normalized.lower()
    positive_terms = ("approval", "approved", "growth", "deal", "agreement", "stimulus", "eases")
    negative_terms = ("ban", "sanction", "attack", "war", "tariff", "shortage", "outage", "strike")
    pos_hits = sum(1 for token in positive_terms if token in lowered)
    neg_hits = sum(1 for token in negative_terms if token in lowered)
    if pos_hits == 0 and neg_hits == 0:
        return 0.0
    total = max(1, pos_hits + neg_hits)
    return max(-1.0, min(1.0, (pos_hits - neg_hits) / total))
