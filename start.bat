@echo off
REM Arranca PiScouting (backend + frontend) y abre el navegador.
title PiScouting launcher
cd /d "%~dp0"

echo Iniciando backend (API) en el puerto 8000...
start "PiScouting - Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --port 8000"

echo Iniciando frontend (web) en el puerto 5173...
start "PiScouting - Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo Esperando a que arranquen los servidores...
timeout /t 6 /nobreak >nul

echo Abriendo la app en el navegador...
start "" http://localhost:5173

echo.
echo PiScouting esta arrancando. Deja abiertas las dos ventanas negras.
echo Para cerrarlo: cierra esas dos ventanas.
echo.
pause
