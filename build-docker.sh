#!/bin/bash

# 简单的 Docker 构建脚本
VERSION=$(cat VERSION 2>/dev/null || echo "latest")

# 构建镜像并同时打上版本标签和 latest 标签
docker build -t gemini-balance:$VERSION -t gemini-balance:latest .

echo "构建完成:"
echo "  - gemini-balance:$VERSION"
echo "  - gemini-balance:latest"
