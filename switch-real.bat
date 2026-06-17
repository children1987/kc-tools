@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo =============================================
echo   切换至实车模式 (Switch to Real Vehicle)
echo =============================================
echo.
python switch-env.py --real
echo 后续操作:
echo   1. 确保 simulators/kc-simulator 已停止
echo   2. 重启 argentina-app
echo.
pause
