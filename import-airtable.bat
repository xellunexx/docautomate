@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Първо пуснете start.bat веднъж.
  pause
  goto :eof
)
if "%~1"=="" (
  if not defined AIRTABLE_TOKEN (
    echo Задайте токена само за този прозорец:  set AIRTABLE_TOKEN=pat...
    echo или подайте CSV файл:                  import-airtable.bat Candidates.csv
    pause
    goto :eof
  )
  ".venv\Scripts\python.exe" -m docautomate.importer --airtable
) else (
  ".venv\Scripts\python.exe" -m docautomate.importer --csv "%~1"
)
pause
