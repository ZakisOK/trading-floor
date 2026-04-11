"""
Backtest validation safeguards.

Problem: LLMs trained on internet data have memorized price history.
A backtest showing 80% win rate might just be the LLM recalling what happened.

Two safeguards:
1. Memorization detection: classify risk based on data recency vs LLM knowledge cutoff.
   If test data predates the cutoff, the LLM may have seen it during training.
2. Holdout contamination check: verify test data is truly out-of-sample for the
   LLM training cutoff. Adjusts Sharpe confidence based on contamination risk.

Research basis: Borges et al. (2025) demonstrated GPT-4 has statistically significant
recall of historical price data. Backtests using LLM signals on pre-cutoff data
cannot be distinguished from the LLM simply recalling outcomes.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backtesting.engine import BacktestResult

# Claude Sonnet 4.5 / Claude 3.7 knowledge cutoff — data before this date
# is likely present in LLM training corpora.
LLM_KNOWLEDGE_CUTOFF = date(2025, 5, 1)

# Symbols with heavy LLM training coverage — widely discussed in financial news,
# Reddit, Twitter, and analysis sites that form the bulk of LLM training corpora.
HIGH_COVERAGE_SYMBOLS = {
    "BTC", "BITCOIN", "ETH", "ETHEREUM", "XRP", "BNB", "SOL",
    "GOLD", "XAU", "GC", "GLD",
    "SPX", "SPY", "QQQ", "NASDAQ", "DJI", "NDX",
    "OIL", "CL", "WTI", "BRENT", "CRUDE",
    "EUR", "USD", "DXY", "GBP", "JPY",
    "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN",
}

# Symbols less likely to dominate LLM training data
LOW_COVERAGE_PREFIXES = {"SHIB", "PEPE", "FLOKI", "WIF", "BONK", "MEME"}


class BacktestValidator:
    """
    Guards against invalid backtest results caused by LLM memorization of historical data.

    The core problem: any LLM (including Claude) trained on internet-scale data has likely
    seen price data, news, and post-mortems for major assets going back years. When you
    backtest an LLM-assisted strategy on historical data, you cannot distinguish between:
      (a) the strategy is genuinely good, OR
      (b) the LLM is recalling what happened and reverse-engineering its signals

    This is not theoretical. Borges et al. (2025) demonstrated that GPT-4's next-day
    price predictions exceeded 55% accuracy on pre-cutoff data — well above chance —
    but dropped to near-random on post-cutoff data. That gap is memorization, not skill.

    This validator classifies risk and annotates results accordingly.
    """

    def check_memorization_risk(
        self,
        symbol: str,
        start_date: date | datetime,
        end_date: date | datetime,
    ) -> dict:
        """
        Assess the probability that LLM memorization is contaminating a backtest.

        Args:
            symbol:     Trading symbol (e.g. "BTC/USDT", "XAU/USD")
            start_date: First bar date in the backtest
            end_date:   Last bar date in the backtest

        Returns:
            dict with keys:
              risk_level (str):        "LOW" | "MEDIUM" | "HIGH"
              reason (str):            Human-readable explanation
              recommended_action (str): What to do about it
        """
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()

        # Normalize the symbol to extract the base asset
        symbol_upper = symbol.upper().replace("/", "").replace("-", "").replace("_", "")
        base = (
            symbol_upper
            .replace("USDT", "").replace("USD", "").replace("BUSD", "")
            .replace("BTC", "", 1) if not symbol_upper.startswith("BTC") else symbol_upper
        )
        # Re-check: if the full symbol IS BTC-related, keep it
        base = symbol_upper.replace("USDT", "").replace("BUSD", "").replace("USDC", "")

        is_high_coverage = (
            base in HIGH_COVERAGE_SYMBOLS
            or any(h in symbol_upper for h in HIGH_COVERAGE_SYMBOLS)
        )
        is_low_coverage = any(symbol_upper.startswith(p) for p in LOW_COVERAGE_PREFIXES)

        data_before_cutoff = end_date < LLM_KNOWLEDGE_CUTOFF
        data_spans_cutoff = start_date < LLM_KNOWLEDGE_CUTOFF <= end_date
        data_after_cutoff = start_date >= LLM_KNOWLEDGE_CUTOFF

        # --- HIGH risk ---
        if data_before_cutoff and is_high_coverage:
            return {
                "risk_level": "HIGH",
                "reason": (
                    f"{symbol} is a widely-covered asset and the full backtest window "
                    f"({start_date} to {end_date}) falls before the LLM knowledge cutoff "
                    f"({LLM_KNOWLEDGE_CUTOFF}). The LLM almost certainly encountered this "
                    f"price history during training. Results cannot be trusted at face value."
                ),
                "recommended_action": (
                    "Re-run on post-cutoff data (after May 2025). "
                    "Run walk-forward validation. "
                    "Treat the Sharpe ratio as an upper bound only."
                ),
            }

        if data_before_cutoff and not is_low_coverage:
            return {
                "risk_level": "HIGH",
                "reason": (
                    f"The full backtest window ({start_date} to {end_date}) predates "
                    f"the LLM knowledge cutoff ({LLM_KNOWLEDGE_CUTOFF}). "
                    f"Any LLM-influenced signal on {symbol} may reflect memorization."
                ),
                "recommended_action": (
                    "Use post-cutoff data where possible. "
                    "Apply a 50%+ discount to the reported Sharpe ratio. "
                    "Validate on live paper-traded data before committing capital."
                ),
            }

        # --- MEDIUM risk ---
        if data_spans_cutoff and is_high_coverage:
            return {
                "risk_level": "MEDIUM",
                "reason": (
                    f"The backtest window straddles the LLM knowledge cutoff. "
                    f"Data from {start_date} to {LLM_KNOWLEDGE_CUTOFF} is potentially "
                    f"memorized. {symbol} has high training data coverage."
                ),
                "recommended_action": (
                    "Split analysis into pre- and post-cutoff segments. "
                    "Weight post-cutoff performance more heavily in your assessment. "
                    "Run walk-forward validation."
                ),
            }

        if is_high_coverage and not data_after_cutoff:
            return {
                "risk_level": "MEDIUM",
                "reason": (
                    f"{symbol} is heavily covered in LLM training data "
                    f"(BTC, ETH, gold, major indices dominate financial news corpora). "
                    f"Even partial in-sample overlap creates memorization risk."
                ),
                "recommended_action": (
                    "Use walk-forward validation to confirm out-of-sample performance. "
                    "Compare against a buy-and-hold baseline. "
                    "Paper trade before live deployment."
                ),
            }

        # --- LOW risk ---
        if data_after_cutoff:
            return {
                "risk_level": "LOW",
                "reason": (
                    f"Backtest window ({start_date} to {end_date}) starts after the LLM "
                    f"knowledge cutoff ({LLM_KNOWLEDGE_CUTOFF}). "
                    f"This data was not available during LLM training."
                ),
                "recommended_action": (
                    "Standard statistical validation applies. "
                    "Walk-forward validation is still recommended."
                ),
            }

        return {
            "risk_level": "LOW",
            "reason": (
                f"{symbol} has limited coverage in LLM training data. "
                "Memorization risk is low, but not zero."
            ),
            "recommended_action": "Standard statistical validation applies.",
        }

    def validate_backtest_result(
        self,
        result: "BacktestResult",
        risk_level: str,
    ) -> dict:
        """
        Annotate a BacktestResult with validity flags based on memorization risk.

        HIGH risk:   halves confidence in Sharpe ratio, adds contamination warning.
        MEDIUM risk: applies 25% confidence penalty to Sharpe.
        LOW risk:    no adjustment — standard statistical caveats still apply.

        Args:
            result:     The BacktestResult to annotate
            risk_level: Output of check_memorization_risk()["risk_level"]

        Returns:
            dict with validity metadata and adjusted Sharpe estimate
        """
        sharpe = result.metrics.sharpe_ratio
        total_trades = result.metrics.total_trades

        validity: dict = {
            "risk_level": risk_level,
            "is_trustworthy": risk_level == "LOW",
            "sharpe_confidence_penalty_pct": 0,
            "adjusted_sharpe": sharpe,
            "warnings": [],
            "labels": [],
        }

        # Too few trades = no statistical power regardless of risk level
        if total_trades < 30:
            validity["warnings"].append(
                f"Only {total_trades} trades. Results are not statistically significant. "
                "A minimum of 30 closed trades is recommended for any confidence."
            )

        if risk_level == "HIGH":
            validity["sharpe_confidence_penalty_pct"] = 50
            validity["adjusted_sharpe"] = round(sharpe * 0.5, 4)
            validity["labels"].append("MEMORIZATION_RISK_HIGH")
            validity["is_trustworthy"] = False
            validity["warnings"].append(
                "HIGH memorization risk: the LLM likely saw this price data during training. "
                "The Sharpe ratio has been halved as a conservative adjustment. "
                "Do not use these results to size real positions."
            )

        elif risk_level == "MEDIUM":
            validity["sharpe_confidence_penalty_pct"] = 25
            validity["adjusted_sharpe"] = round(sharpe * 0.75, 4)
            validity["labels"].append("MEMORIZATION_RISK_MEDIUM")
            validity["is_trustworthy"] = False
            validity["warnings"].append(
                "MEDIUM memorization risk: widely-covered asset or partial in-sample period. "
                "Sharpe ratio reduced by 25% as a conservative adjustment."
            )

        # A Sharpe above 3 on historical LLM-influenced data is a red flag
        if sharpe > 3.0 and risk_level != "LOW":
            validity["warnings"].append(
                f"Sharpe ratio of {sharpe:.2f} is suspiciously high. "
                "This is a common signature of LLM memorization or data snooping bias. "
                "Independently verify with a non-LLM baseline strategy."
            )

        return validity
