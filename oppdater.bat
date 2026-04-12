@echo off
cd C:\Users\Andreas\aksjer
python analyze_portfolio.py
git add index.html
git commit -m "Daglig oppdatering"
git push
echo Ferdig! Rapporten er oppdatert.
pause