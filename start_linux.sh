#!/bin/bash
# RPA_GROUP Linux/Mac 启动脚本

echo "=========================================="
echo "  RPA_GROUP 自动化服务启动脚本"
echo "=========================================="
echo ""

# 检查 conda 是否安装
if ! command -v conda &> /dev/null; then
    echo "错误: 未找到 conda 命令"
    echo "请先安装 Miniconda 或 Anaconda"
    exit 1
fi

# 检查环境是否存在
if ! conda env list | grep -q "RPA_GROUP"; then
    echo "警告: RPA_GROUP 环境不存在"
    echo "正在创建环境..."
    conda env create -f environment.yml
    if [ $? -ne 0 ]; then
        echo "错误: 环境创建失败"
        exit 1
    fi
fi

# 激活环境
echo "激活 Conda 环境: RPA_GROUP"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate RPA_GROUP

# 检查配置文件
if [ ! -f ".env" ]; then
    echo ""
    echo "警告: 未找到 .env 配置文件"
    echo "请复制 .env.example 为 .env 并填写配置"
    echo ""
    read -p "按任意键退出..."
    exit 1
fi

if [ ! -f "config.py" ]; then
    echo ""
    echo "警告: 未找到 config.py 配置文件"
    echo "请复制 config.py.example 为 config.py"
    echo ""
    read -p "按任意键退出..."
    exit 1
fi

# 启动服务
echo ""
echo "启动 FastAPI 服务..."
echo "访问地址: http://127.0.0.1:8000"
echo "API 文档: http://127.0.0.1:8000/docs"
echo "队列监控: http://127.0.0.1:8000/queue-monitor"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

uvicorn RPA:app --host 0.0.0.0 --port 8000