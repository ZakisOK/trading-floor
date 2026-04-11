@echo off
cd /d C:\Users\zakob\projects\trading-floor\frontend
git add -A
git commit -m "fix: rename next.config.ts to next.config.mjs for Next.js compatibility"
git push origin main
git log --oneline -3
