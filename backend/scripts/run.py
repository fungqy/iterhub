#!/usr/bin/env python3
"""迭代看板服务启动脚本（跨平台：Linux / macOS / Windows）

用法:
    python scripts/run.py
    uv run python scripts/run.py
"""

from __future__ import annotations

import io
import logging.config
import os
import sys
from pathlib import Path


def _load_env(env_path: Path) -> None:
    """加载 .env 文件到 os.environ（不覆盖已有值）"""
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        # 去掉首尾成对引号
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _check_db_config() -> None:
    """检查必需的数据库配置，缺失则打印帮助并退出"""
    if os.environ.get("MSQL_DSN"):
        return

    print("❌ 启动失败: 数据库配置缺失", file=sys.stderr)
    print(file=sys.stderr)
    print("未设置环境变量 MSQL_DSN（完整 SQLAlchemy URL）", file=sys.stderr)
    print(file=sys.stderr)
    print("请在 backend/.env 文件中配置以下环境变量:", file=sys.stderr)
    print("  MSQL_DSN=mysql+pymysql://user:password@host:port/database", file=sys.stderr)
    print(file=sys.stderr)
    print("示例 .env 文件内容:", file=sys.stderr)
    print("  MSQL_DSN=mysql+pymysql://your_user:your_password@localhost:3306/your_database", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    # 切到项目根目录，使 "src.api.main:app" 能被解析
    os.chdir(project_root)
    sys.path.insert(0, str(project_root))

    # 加载 .env
    _load_env(project_root / ".env")

    # 配置检查
    _check_db_config()

    # 默认值
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    log_file = os.environ.get("LOG_FILE", str(project_root / "logs" / "app.log"))

    # 创建日志目录
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    # logging.conf 存在则使用，否则用 uvicorn 默认
    log_config_path = project_root / "logging.conf"
    if log_config_path.exists():
        # uvicorn 走 fileConfig() 时按系统 locale（中文 Windows = GBK）解码，
        # conf 里的中文注释会触发 UnicodeDecodeError；fileConfig 的 encoding
        # 参数 3.12 才有，这里自己以 UTF-8 读入、用文件对象模式喂给它。
        logging.config.fileConfig(
            io.StringIO(log_config_path.read_text(encoding="utf-8")),
            disable_existing_loggers=False,
        )
        # 已自行完成日志配置，传 None 避免 uvicorn 重复配置
        log_config = None
    else:
        log_config = None

    print(f"Starting iterhub service on {host}:{port} ...")

    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
