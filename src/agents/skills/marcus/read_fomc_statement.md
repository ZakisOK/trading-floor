---
name: read_fomc_statement
description: Parse an FOMC statement and dot-plot delta against the prior meeting and recent Fed speak
triggers: [fomc, fed_statement, rate_decision, dot_plot]
requires_tools: [fetch_url, query_memory, fred_api]
cost_tokens: 2200
---
## When to use
Use at 14:00 ET on every scheduled FOMC decision day, immediately when the statement drops. Also use on unscheduled inter-meeting actions. Do not fire on Fed governor speeches — route those through `macro_regime_shift`.

## Procedure
1. Fetch the statement text and the Summary of Economic Projections PDF. Save both under `group_id=marcus` as source_description "fomc_<date>".
2. Diff the statement paragraph-by-paragraph against the prior meeting. Flag hawkish shifts (stronger language on "persistent inflation", removed "patient"), dovish shifts (added "closely monitor", softened growth language), and terminal-rate language changes.
3. Parse the dot-plot median for end-of-year and terminal rate. Compute delta vs the prior SEP. More than 2 dots moving in the same direction is a regime signal.
4. Check fed funds futures 30 minutes pre- and post-release. Move > 6 bps in an intended-meeting contract implies surprise.
5. Pull past 4 FOMC reactions from firm memory. If reaction size/direction is inconsistent with this move, note regime uncertainty.

## Rubric / Decision rule
Hawkish surprise: dot-plot up ≥25 bps relative to consensus and statement removes patience language → short front-end rates, long USD, short high-duration equities. Dovish surprise: dots down or dissent for a cut → steepen curve, long growth. Match print: trade mean-reversion of the pre-release move.

## Post-conditions
- Writes `fomc_reading` episode to marcus memory with hawkish/dovish/match classification
- Emits signal on ZN, ZQ, DXY, and XLK only if confidence > 0.65
- Shares classification to firm memory under `group_id=firm` for Rex and Diana
