@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Docautomate

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython

if not exist ".venv\Scripts\python.exe" (
  echo Първо стартиране: подготвям програмата. Отнема няколко минути...
  %PY% -m venv .venv
  if errorlevel 1 goto :nopython
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 goto :fail
if not exist ".venv\ocr-done" (
  echo Инсталирам разчитането на паспорти...
  ".venv\Scripts\python.exe" -m pip install -q -r requirements-ocr.txt && echo ok> ".venv\ocr-done"
  if not exist ".venv\ocr-done" echo Разчитането на паспорти не се инсталира. Данните може да се въвеждат ръчно.
)

".venv\Scripts\python.exe" -m docautomate %*
goto :eof

:nopython
echo.
echo Не е намерен Python. Инсталирайте Python 3.11 или по-нов от https://www.python.org/downloads/
echo При инсталацията отметнете "Add python.exe to PATH". После пуснете start.bat отново.
pause
goto :eof

:fail
echo.
echo Инсталацията не успя. Проверете връзката с интернет и пуснете start.bat отново.
pause
