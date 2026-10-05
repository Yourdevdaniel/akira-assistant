@echo off
REM Sobe o Akira no Telegram. Feche esta janela para parar.
REM O gateway do OpenJarvis nao funciona no Windows, por isso o runner proprio.

set "PROJ=%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
set "PYTHONIOENCODING=utf-8"

REM Variaveis do .env (ver .env.example). Linhas com # sao ignoradas.
if exist "%PROJ%.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%PROJ%.env") do set "%%A=%%B"
)
if not defined OPENJARVIS_DIR set "OPENJARVIS_DIR=%PROJ%openjarvis"
set "OJ=%OPENJARVIS_DIR%"

if not exist "%OJ%\.venv" (
    echo ERRO: ambiente do OpenJarvis nao encontrado em %OJ%
    echo Veja "Run it" no README.
    pause
    exit /b 1
)
if not exist "%PROJ%logs" mkdir "%PROJ%logs"

echo Subindo o Akira... (leva uns 20 segundos)
echo Log: %PROJ%logs\akira-telegram.log
echo.

cd /d "%OJ%"
uv run python -X utf8 -u "%PROJ%runner\akira_telegram.py" 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%PROJ%logs\akira-telegram.log'"

echo.
echo Akira parou.
pause
