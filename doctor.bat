@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ================================================
echo   Argentina Project - 现场诊断工具
echo   阿根廷项目环境诊断
echo ================================================
echo.
python doctor.py
echo.
echo 诊断完成。报告已保存到当前目录。
echo.
pause
