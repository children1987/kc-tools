@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo =============================================
echo   切换至模拟器模式 (Switch to Simulator)
echo =============================================
echo.
python switch-env.py --sim
echo 后续操作:
echo   1. 启动 simulators/kc-simulator
echo   2. 重启 argentina-app
echo.
pause
