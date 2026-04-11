"""
Sentiment Analyst — FinBERT-powered financial news sentiment agent.
FinBERT is a BERT model fine-tuned on financial text.
Produces Sharpe ~3.0 in academic backtests (most validated LLM alpha source).

Uses transformers library with ProsusAI/finbert model.
Falls back to VADER financial lexicon if transformers not installed.
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.base import AgentState, BaseAgent
from src.core.config import settings
from src.data.feeds.news_feed import get_news_feed

logger = structlog.get_logger()

# ------------------------------------------------------------------
# Backend detection — FinBERT vs VADER
# ------------------------------------------------------------------

_FINBERT_AVAILABLE = False
_VADER_AVAILABLE = False

try:
    from transformers import pipeline  # type: ignore[import]
    _FINBERT_AVAILABLE = True
except ImportError:
    pass

if not _FINBERT_AVAILABLE:
    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer  # type: ignore[import]
        import nltk  # type: ignore[import]
        _VADER_AVAILABLE = True
    except ImportError:
        pass

# Thresholds
MIN_HEADLINES = 3          # Below this, emit no signal (thin news)
LONG_THRESHOLD = 0.15      # Aggregate score ≥ this → LONG
SHORT_THRESHOLD = -0.15    # Aggregate score ≤ this → SHORT
AGE_DISCOUNT_RATE = 0.04   # Confidence penalty per hour of headline age

FINBERT_MODEL = "ProsusAI/finbert"

# Financial keyword scores for keyword-only fallback (when both VADER and FinBERT unavailable)
POSITIVE_KEYWORDS = {
    "surge": 0.7, "rally": 0.65, "breakout": 0.6, "beat": 0.55, "bullish": 0.7,
    "gain": 0.45, "rise": 0.4, "record": 0.5, "growth": 0.45, "profit": 0.5,
    "upgrade": 0.6, "buy": 0.5, "outperform": 0.6, "approval": 0.55,
}
NEGATIVE_KEYWORDS = {
    "crash": -0.75, "plunge": -0.7, "collapse": -0.75, "sell": -0.45,
    "bearish": -0.65, "downgrade": -0.6, "loss": -0.5, "decline": -0.45,
    "warning": -0.5, "risk": -0.3, "default": -0.65, "fraud": -0.7,
    "regulatory": -0.4, "ban": -0.6, "lawsuit": -0.55,
}


# ------------------------------------------------------------------
# FinBERT singleton
# ------------------------------------------------------------------

_finbert_pipeline: Any = None


def _get_finbert() -> Any:
    global _finbert_pipeline
    if _finbert_pipeline is None:
        logger.info("finbert_loading", model=FINBERT_MODEL)
        _finbert_pipeline = pipeline(
            "text-classification",
            model=FINBERT_MODEL,
            top_k=None,       # Return all 3 label scores
            truncation=True,
            max_length=512,
        )
        logger.info("finbert_ready", model=FINBERT_MODEL)
    return _finbert_pipeline


# ------------------------------------------------------------------
# VADER singleton with NLTK corpus check
# ------------------------------------------------------------------

_vader_analyzer: Any = None


def _get_vader() -> Any:
    global _vader_analyzer
    if _vader_analyzer is None:
        import nltk  # type: ignore[import]
        from nltk.sentiment.vader import SentimentIntensityAnalyzer  # type: ignore[import]
        try:
            nltk.data.find("sentiment/vader_lexicon.zip")
        except LookupError:
            nltk.download("vader_lexicon", quiet=True)
        _vader_analyzer = SentimentIntensityAnalyzer()
    return _vader_analyzer


# ------------------------------------------------------------------
# Core scoring functions
# ------------------------------------------------------------------

def _score_with_finbert(texts: list[str]) -> list[dict[str, float]]:
    """Run FinBERT on a batch of texts. Returns list of {positive, negative, neutral}."""
    nlp = _get_finbert()
    results = []
    # FinBERT top_k=None returns list-of-lists of {label, score}
    batch_output = nlp(texts, batch_size=8)
    for item in batch_output:
        scores: dict[str, float] = {}
        for entry in item:
            scores[entry["label"].lower()] = entry["score"]
        results.append(scores)
    return results


def _score_with_vader(texts: list[str]) -> list[dict[str, float]]:
    """Run VADER on texts. Normalises compound [-1,1] into positive/negative/neutral."""
    sia = _get_vader()
    results = []
    for text in texts:
        vs = sia.polarity_scores(text)
        compound = vs["compound"]  # -1 to +1
        # Convert to pseudo-FinBERT format
        if compound >= 0.05:
            results.append({"positive": 0.5 + compound * 0.5, "negative": 0.1, "neutral": 0.4})
        elif compound <= -0.05:
            results.append({"positive": 0.1, "negative": 0.5 + abs(compound) * 0.5, "neutral": 0.4})
        else:
            results.append({"positive": 0.2, "negative": 0.2, "neutral": 0.6})
    return results


def _score_with_keywords(texts: list[str]) -> list[dict[str, float]]:
    """Ultra-lightweight keyword fallback when no NLP library is available."""
    results = []
    for text in texts:
        lower = text.lower()
        score = 0.0
        for kw, val in POSITIVE_KEYWORDS.items():
            if kw in lower:
                score += val
        for kw, val in NEGATIVE_KEYWORDS.items():
            if kw in lower:
                score += val  # val is negative
        score = max(-1.0, min(1.0, score))
        if score > 0.05:
            results.append({"positive": 0.5 + score * 0.5, "negative": 0.1, "neutral": 0.4})
        elif score < -0.05:
            results.append({"positive": 0.1, "negative": 0.5 + abs(score) * 0.5, "neutral": 0.4})
        else:
            results.append({"positive": 0.2, "negative": 0.2, "neutral": 0.6})
    return results


def _age_discount(published_at: str, now: datetime) -> float:
    """Return a [0, 1] multiplier. Older headlines get lower weight."""
    if not published_at:
        return 0.5
    try:
        pub = datetime.fromisoformat(published_at)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=UTC)
        hours_old = (now - pub).total_seconds() / 3600
        return math.exp(-AGE_DISCOUNT_RATE * hours_old)
    except (ValueError, TypeError):
        return 0.5


def _determine_backend() -> str:
    forced = settings.sentiment_backend.lower()
    if forced == "finbert" and _FINBERT_AVAILABLE:
        return "finbert"
    if forced == "vader" and _VADER_AVAILABLE:
        return "vader"
    # Auto-select best available
    if _FINBERT_AVAILABLE:
        return "finbert"
    if _VADER_AVAILABLE:
        return "vader"
    return "keywords"


# ------------------------------------------------------------------
# SentimentAnalystAgent
# ------------------------------------------------------------------

class SentimentAnalystAgent(BaseAgent):
    """Generates LONG/SHORT signals from financial news sentiment.

    Signal emission rules:
    - Requires >= MIN_HEADLINES (3) headlines to emit any signal
    - Aggregate score >= LONG_THRESHOLD (0.15) → LONG
    - Aggregate score <= SHORT_THRESHOLD (-0.15) → SHORT
    - Otherwise → no signal emitted (NEUTRAL state, no noise)

    Confidence = avg(top_label_probability) × avg(age_discount_factor)
    This rewards fresh, high-conviction headlines.
    """

    def __init__(self) -> None:
        super().__init__("sentiment_analyst", "Sentiment Analyst", "News Sentiment")
        self._backend: str = _determine_backend()
        logger.info(
            "sentiment_analyst_init",
            backend=self._backend,
            finbert_available=_FINBERT_AVAILABLE,
            vader_available=_VADER_AVAILABLE,
        )

    def analyze_sentiment(self, headlines: list[dict]) -> dict:
        """Score a list of headline dicts and return aggregated sentiment.

        Args:
            headlines: list of {title, description, published_at, source, symbol}

        Returns:
            {sentiment, score, confidence, signal_count, backend}
            sentiment: "positive" | "negative" | "neutral"
            score: float in [-1, 1] — drives LONG/SHORT decision
            confidence: float in [0, 1] — avg probability × avg freshness
            signal_count: int — headlines that contributed
            backend: str — "finbert" | "vader" | "keywords"
        """
        if not headlines:
            return {
                "sentiment": "neutral", "score": 0.0,
                "confidence": 0.0, "signal_count": 0, "backend": self._backend,
            }

        now = datetime.now(UTC)
        texts = [
            f"{h.get('title', '')} {h.get('description', '')}".strip()
            for h in headlines
        ]

        # Score via chosen backend
        if self._backend == "finbert":
            scores = _score_with_finbert(texts)
        elif self._backend == "vader":
            scores = _score_with_vader(texts)
        else:
            scores = _score_with_keywords(texts)

        # Build weighted aggregate
        total_score = 0.0
        total_confidence = 0.0
        total_weight = 0.0

        for headline, score_dict in zip(headlines, scores):
            age_w = _age_discount(headline.get("published_at", ""), now)
            pos = score_dict.get("positive", 0.0)
            neg = score_dict.get("negative", 0.0)
            # Direction score: positive pushes toward +1, negative toward -1
            directional = pos - neg
            top_prob = max(score_dict.values())

            total_score += directional * age_w
            total_confidence += top_prob * age_w
            total_weight += age_w

        if total_weight == 0:
            agg_score = 0.0
            agg_confidence = 0.0
        else:
            agg_score = total_score / total_weight
            agg_confidence = total_confidence / total_weight

        # Determine overall sentiment label
        if agg_score >= 0.05:
            sentiment = "positive"
        elif agg_score <= -0.05:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "sentiment": sentiment,
            "score": round(agg_score, 4),
            "confidence": round(agg_confidence, 4),
            "signal_count": len(headlines),
            "backend": self._backend,
        }

    async def analyze(self, state: AgentState) -> AgentState:
        """Fetch news for the current symbol, score sentiment, emit signal if threshold met."""
        market = state.get("market_data") or {}
        symbol = market.get("symbol", "UNKNOWN")

        try:
            feed = get_news_feed()
            headlines = await feed.get_headlines(symbol, hours_back=24)

            result = self.analyze_sentiment(headlines)
            score = result["score"]
            confidence = result["confidence"]
            signal_count = result["signal_count"]
            backend = result["backend"]
            sentiment = result["sentiment"]

            log = logger.bind(
                symbol=symbol,
                sentiment=sentiment,
                score=score,
                confidence=confidence,
                headlines=signal_count,
                backend=backend,
            )

            # Gate: need at least MIN_HEADLINES to emit a signal
            if signal_count < MIN_HEADLINES:
                log.info("sentiment_thin_news_skip")
                return state

            # Determine direction from threshold
            if score >= LONG_THRESHOLD:
                direction = "LONG"
            elif score <= SHORT_THRESHOLD:
                direction = "SHORT"
            else:
                log.info("sentiment_neutral_no_signal", threshold=LONG_THRESHOLD)
                return state

            thesis = (
                f"FinBERT ({backend}) scored {signal_count} headlines: "
                f"aggregate sentiment={sentiment} (score={score:.3f}). "
                f"News sources point {direction} with confidence {confidence:.2f}."
            )

            await self.emit_signal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                thesis=thesis,
                strategy="news_sentiment",
            )

            log.info("sentiment_signal_emitted", direction=direction)

            updated = dict(state)
            updated["signals"] = list(state.get("signals", [])) + [
                {
                    "agent": self.name,
                    "direction": direction,
                    "confidence": confidence,
                    "thesis": thesis,
                    "sentiment_score": score,
                    "headline_count": signal_count,
                    "backend": backend,
                }
            ]
            return AgentState(**updated)

        except Exception as exc:
            logger.error("sentiment_analyst_error", symbol=symbol, error=str(exc))
            return state
