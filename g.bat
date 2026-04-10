@echo off
cd /d C:\Users\zakob\projects\trading-floor
git add -A
git commit -m "chore: clean up temp batch files"
del g.bat
git log --oneline
