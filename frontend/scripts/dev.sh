#!/bin/bash

# 前端开发环境启动脚本

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 设置工作目录
cd "$PROJECT_ROOT"

# 加载 .env 文件（如果存在）
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# 检查 Node.js 是否安装
check_node() {
    if ! command -v node &> /dev/null; then
        echo "❌ 启动失败: 未安装 Node.js"
        echo ""
        echo "请先安装 Node.js (推荐版本 18.x 或更高)"
        echo "安装方式:"
        echo "  - 使用 nvm: nvm install 18 && nvm use 18"
        echo "  - Ubuntu: sudo apt install nodejs npm"
        echo "  - macOS: brew install node"
        exit 1
    fi

    NODE_VERSION=$(node -v | cut -d 'v' -f 2 | cut -d '.' -f 1)
    if [ "$NODE_VERSION" -lt 18 ]; then
        echo "⚠️  警告: Node.js 版本过低 (当前: $(node -v))"
        echo "推荐使用 Node.js 18.x 或更高版本"
    fi
}

# 检查依赖是否安装
check_dependencies() {
    if [ ! -d "node_modules" ]; then
        echo "📦 检测到未安装依赖，正在安装..."
        npm install
        if [ $? -ne 0 ]; then
            echo "❌ 依赖安装失败"
            exit 1
        fi
    fi
}

# 显示配置信息
show_config() {
    local api_host=${VITE_API_HOST:-"http://localhost:8000"}
    local port=${PORT:-"3000"}

    echo "======================================"
    echo "  前端开发服务器启动中..."
    echo "======================================"
    echo ""
    echo "配置信息:"
    echo "  - 服务端口: $port"
    echo "  - 后端 API: $api_host"
    echo ""
    echo "访问地址: http://localhost:$port"
    echo ""
    echo "按 Ctrl+C 停止服务"
    echo "======================================"
    echo ""
}

# 执行检查
check_node
check_dependencies
show_config

# 默认配置
PORT=${PORT:-"3000"}

# 启动开发服务器
exec npm run dev -- --host 0.0.0.0 --port "$PORT"
