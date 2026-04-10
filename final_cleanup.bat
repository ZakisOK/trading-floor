@echo off
cd /d C:\Users\zakob\projects\trading-floor
del cleanup.bat
git add -A
git commit -m "chore: remove temp batch files"
git log --oneline
