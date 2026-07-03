@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ================================================
echo   Switch to Simulator
echo ================================================
echo.
echo   Files to update:
echo     - model.xml           navHost ^& qrHost -^> 127.0.0.1
echo     - fork_udp.py         controller_ip -^> 127.0.0.1
echo.
python switch-env.py --sim
if errorlevel 1 (
    echo.
    echo [ERR] Switch failed. Check errors above.
    pause
    exit /b 1
)
echo.
echo --------------------------------------------------
echo   Next steps:
echo --------------------------------------------------
echo.
echo   1. Start simulators/kc-simulator
echo   2. Restart openTCS Kernel
echo   3. Restart argentina-app
echo.
pause
