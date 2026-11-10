@echo off
REM Inicia el nodo de scraping de PlateGuardAI (ingesta continua cada 2 horas)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
:inicio
python nodo_scraping.py --cada 120
REM Si el nodo se cierra por un error, se reinicia en 30 segundos
echo El nodo se detuvo. Reiniciando en 30 segundos... (cierre esta ventana para detenerlo)
timeout /t 30 /nobreak >nul
goto inicio
