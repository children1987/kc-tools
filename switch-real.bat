@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ================================================
echo   Switch to Real Vehicle
echo ================================================
echo.
echo   Files to update:
echo     - model.xml           navHost ^& qrHost -^> 192.168.100.x
echo     - fork_udp.py         controller_ip -^> 192.168.100.200
echo.
python switch-env.py --real
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
echo   1. Stop simulators/kc-simulator if running
echo   2. Test network: ping 192.168.100.178
echo   3. Restart openTCS Kernel
echo   4. Restart argentina-app
echo.
pause
