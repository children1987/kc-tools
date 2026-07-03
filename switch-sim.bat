@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo =============================================
echo   切换至模拟器模式 (Switch to Simulator)
echo =============================================
echo.
echo   切换内容:
echo     - model.xml          navHost ^& qrHost ^> 127.0.0.1
echo     - model-zhongwu.xml  navHost ^& qrHost ^> 127.0.0.1
echo     - fork_udp.py        controller_ip ^> 127.0.0.1
echo.
python switch-env.py --sim
if errorlevel 1 (
    echo.
    echo [ERR] 切换失败，请检查上方错误信息
    pause
    exit /b 1
)
echo.
echo ─────────────────────────────────────────────
echo   切换完成！请按以下顺序操作:
echo ─────────────────────────────────────────────
echo.
echo   1. 启动 simulators/kc-simulator
echo   2. 重启 openTCS Kernel
echo   3. 重启 argentina-app
echo.
pause
