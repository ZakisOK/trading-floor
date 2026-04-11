@echo off
title The Trading Floor — Paper Trading
color 0A
echo.
echo  Starting paper trading loop...
echo  Agents: Marcus, Vera, Rex, Diana, Atlas, Sage
echo  Symbols: BTC/USDT, ETH/USDT, SOL/USDT
echo  Cycle: every 5 minutes
echo  Mode: COMMANDER (you approve all trades)
echo.
cd /d C:\Users\zakob\projects\trading-floor
call .venv\Scripts\activate.bat
python scripts\run_paper_trading.py
pause
