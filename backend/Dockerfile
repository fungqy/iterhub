FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv

# 依赖只用 uv.lock 装：锁文件是唯一的版本真相源，pyproject.toml 仅提供工程元数据。
# ⚠ 这里不能改用 `uv sync`：.dockerignore 排除了 README.md，而 pyproject.toml 的
#   readme 字段指向它，uv sync 需要构建项目元数据 ⇒ 会因缺 README 而失败。
#   `uv export → uv pip install` 不需要 README，已验证可用。
COPY pyproject.toml uv.lock ./

# --frozen：严格按 uv.lock 安装，不重新解析依赖 → 构建可复现
# --no-emit-project：不安装 iterhub 自身（代码由 scripts/run.py 注入的 sys.path 加载）
# 导出的 requirements.txt 带 sha256，uv pip 安装时会做哈希校验
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && uv pip install --system --no-cache -r requirements.txt \
    && rm -f requirements.txt

COPY src/ ./src/
COPY logging.conf .
COPY scripts/run.py ./scripts/

RUN mkdir -p logs

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

# run.py 自带 chdir / sys.path 注入 / .env 加载 / logging.conf 配置，
# 与本地 `python scripts/run.py` 的启动行为一致
CMD ["python", "scripts/run.py"]
