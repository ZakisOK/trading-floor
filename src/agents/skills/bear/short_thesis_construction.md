---
name: short_thesis_construction
description: Build a short thesis with named mechanism, dated catalysts, and pre-set cover triggers
triggers: [short, short_thesis, overvalued, accounting_concern]
requires_tools: [fetch_fundamentals, fetch_filings, fetch_ohlcv, query_memory]
cost_tokens: 2200
---
## When to use
Use when Bear or Marcus flags an overvalued or deteriorating name, when short-interest-to-borrow-cost math is favorable, or when a known-bad catalyst (earnings, regulatory, debt maturity) is in the 30–90 day window.

## Procedure
1. Name the mechanism. Valid mechanisms: deteriorating fundamentals (decelerating growth + margin compression), accounting irregularities (receivables-to-revenue, inventory-to-COGS trending), debt cliff (maturing debt > cash + FCF runway), regulatory threat, obsolescence, overvaluation (multiple > 1.5× peer median without growth to justify).
2. Show the math. Pull the last eight quarters of the relevant metric. A valid short thesis shows a trend, not a snapshot.
3. List dated catalysts. Earnings dates, investor days, debt maturity dates, regulatory deadlines, lock-up expirations. Each must have a known date and expected direction.
4. Check short-side mechanics. Borrow availability, borrow cost (reject if >15% annualized for a multi-week trade), hard-to-borrow status, and short-interest crowding. Crowded shorts (SI > 20% of float) are squeeze candidates — require an imminent catalyst to justify entry.
5. Set cover triggers. A fundamental cover: the mechanism disconfirms (revenue re-accelerates, debt refinanced). A price cover: the stop level (typically swing-high + 1 × ATR). A time cover: if catalyst passes without downside reaction, cover regardless of price.

## Rubric / Decision rule
Require all five: named mechanism, trend math, dated catalyst, acceptable borrow, pre-set cover triggers. Missing any one rejects the short. Size is half of long-side Kelly to account for squeeze risk and borrow carry.

## Post-conditions
- Writes `short_thesis` episode to bear memory with mechanism, catalyst dates, borrow cost, cover triggers
- Produces structured short signal through Diana — she sizes with the crowding discount applied
- Stores cover triggers in firm memory so Atlas can auto-buy-to-cover when any fires
