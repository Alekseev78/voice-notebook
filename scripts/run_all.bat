@echo off

rem Run all microservices in parallel using start command.
rem Adjust ports if needed via environment variables.

setlocal EnableDelayedExpansion

:: Gateway on 8000 by default
if not defined VOICENOTEB_GW_PORT set VOICENOTEB_GW_PORT=8000
:: Notes Service on 8002
if not defined VOICENOTEB_NOTES_PORT set VOICENOTEB_NOTES_PORT=8002
:: Search Service on 8003
if not defined VOICENOTEB_SEARCH_PORT set VOICENOTEB_SEARCH_PORT=8003
:: STT Service on 8001
if not defined VOICENOTEB_STT_PORT set VOICENOTEB_STT_PORT=8001

echo Starting services...

start "Gateway" cmd /c "python -m uvicorn backend.gateway.main:app --host 0.0.0.0 --port !VOICENOTEB_GW_PORT!"
timeout /t 2 >nul
start "STT"    cmd /c "python -m uvicorn backend.stt_service.main:app --host 0.0.0.0 --port !VOICENOTEB_STT_PORT!"
timeout /t 2 >nul
start "Notes"   cmd /c "python -m uvicorn backend.notes_service.main:app --host 0.0.0.0 --port !VOICENOTEB_NOTES_PORT!"
timeout /t 2 >nul
start "Search"  cmd /c "python -m uvicorn backend.search_service.main:app --host 0.0.0.0 --port !VOICENOTEB_SEARCH_PORT!"

echo All services started.
pause