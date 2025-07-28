@echo off
REM 简单的 Docker 构建脚本
if exist "VERSION" (
    set /p VERSION=<VERSION
) else (
    set VERSION=latest
)
docker build -t gemini-balance:%VERSION% .
echo 构建完成: gemini-balance:%VERSION%
