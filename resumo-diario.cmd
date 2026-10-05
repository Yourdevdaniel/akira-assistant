@echo off
REM Gera o resumo do dia e manda no Telegram (texto + audio).
REM Chamado pelo Agendador de Tarefas do Windows.

set "PROJ=%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
set "PYTHONIOENCODING=utf-8"

REM Variaveis do .env (ver .env.example). Linhas com # sao ignoradas.
if exist "%PROJ%.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%PROJ%.env") do set "%%A=%%B"
)
if not defined OPENJARVIS_DIR set "OPENJARVIS_DIR=%PROJ%openjarvis"
set "OJ=%OPENJARVIS_DIR%"
if not exist "%PROJ%logs" mkdir "%PROJ%logs"

cd /d "%OJ%"
uv run python -X utf8 -u "%PROJ%runner\resumo_telegram.py" >> "%PROJ%logs\resumo-diario.log" 2>&1
