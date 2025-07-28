#!/bin/bash

# 简单的 Docker 构建脚本
VERSION=$(cat VERSION 2>/dev/null || echo "latest")
docker build -t gemini-balance:$VERSION .
echo "构建完成: gemini-balance:$VERSION"
