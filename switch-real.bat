@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo =============================================
echo   切换至实车模式 (Switch to Real Vehicle)
echo =============================================
echo.
echo   切换内容:
echo     - model.xml          navHost ^& qrHost ^> 192.168.100.x
echo     - model-zhongwu.xml  navHost ^& qrHost ^> 192.168.100.x
echo     - fork_udp.py        controller_ip ^> 192.168.100.200
echo.
python switch-env.py --real
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
echo   1. 确认 simulators/kc-simulator 已停止 ^(端口 17804^)
echo   2. 测试网络: ping 192.168.100.178
echo   3. 重启 openTCS Kernel
echo   4. 重启 argentina-app
echo.
pause
