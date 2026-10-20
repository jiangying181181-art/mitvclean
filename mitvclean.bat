@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title mitvclean - 小米电视去臃肿与去广告

cd /d "%~dp0"

REM ---- 找一个可用的 Python 3.9+ ----
set "PY="
where py >nul 2>&1 && (
    py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    where python >nul 2>&1 && (
        python -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=python"
    )
)
if not defined PY (
    echo.
    echo   [!] 没有找到 Python 3.9 或更高版本
    echo.
    echo       请到 https://www.python.org/downloads/ 下载安装，
    echo       安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo.
echo   ============================================================
echo     mitvclean  小米电视去臷肿与去广告
echo   ============================================================
echo.

echo   [1/2] 检查依赖...
%PY% -c "import cryptography" >nul 2>&1
if errorlevel 1 (
    echo         未装 cryptography，将使用内置的纯 Python RSA 实现（慢一点但能用）
) else (
    echo         cryptography 已就绪
)

echo.
echo   [2/2] 启动...
echo.
%PY% -m mitvclean.cli %*
set RC=%ERRORLEVEL%

echo.
if %RC% neq 0 (
    echo   退出码 %RC%
) else (
    echo   完成
)
echo.
pause
endlocal
