---
name: macro_regime_shift
description: Detect a shift in the macro regime (growth/inflation quadrant) and reassess firm-wide positioning
triggers: [regime_shift, macro_surprise, cpi, nfp, pmi, gdp]
requires_tools: [fred_api, fetch_ohlcv, query_memory]
cost_tokens: 2000
---
## When to use
Use when a tier-1 macro print (CPI, PCE, NFP, ISM, GDP, retail sales) surprises by more than 1.5σ vs consensus, or when Marcus's rolling 60-day quadrant classifier flips between Growth-Up-Inflation-Up (reflation), Growth-Up-Inflation-Down (goldilocks), Growth-Down-Inflation-Up (stagflation), and Growth-Down-Inflation-Down (deflation).

## Procedure
1. Pull the surprise series from FRED for: CPI YoY, Core PCE, Unemployment, ISM Manufacturing, ISM Services, Retail Sales Control. Normalize each as z-score vs trailing 24 months.
2. Compute the two factors — growth (avg of ISM + NFP + retail) and inflation (avg of CPI + PCE) — and place today's reading on the quadrant grid.
3. Compare to the 60-day moving quadrant. A confirmed shift requires three consecutive weekly prints in the new quadrant.
4. Check the rate curve response in the same session. Reflation should lift 10y-2y; stagflation flattens the curve with yields up. A mismatch between data and price suggests the market had already repriced.
5. Query firm memory for the last five regime shifts and their 30-day forward return by asset class.

## Rubric / Decision rule
Goldilocks → long duration tech, long IG credit, short USD. Reflation → long energy, materials, banks; short duration. Stagflation → long gold, long short-dated TIPS, short consumer discretionary. Deflation → long long-duration UST, short USD.JPY, short credit. Confidence is capped at 0.7 when only a single tier-1 print has flipped the quadrant.

## Post-conditions
- Writes `regime_snapshot` episode to marcus memory with quadrant label and confidence
- Publishes a `regime_shift` firm-memory note when a new quadrant is confirmed
- Triggers Sage to rerun morning_brief with the new regime tag
