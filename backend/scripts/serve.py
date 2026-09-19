#!/usr/bin/env python3
"""带自愈能力的后端监管进程（supervisor）—— 在 `run.py` 外面包一层循环。

## 为什么需要它

`scripts/run.py` 是**裸启动器**：调一次 `uvicorn.run()` 就返回，进程一没它就没了。
实测过的真实故障形态（2026-09-19）：
  - 后台任务被外部 `taskkill /PID <pid> /F` 打掉 ⇒ 服务直接下线，
    要等到有人发现、再手动 `netstat` 认领端口、再手动拉起；
  - 只要没人看着，"崩溃一次"就等于"一直不可用"。

本脚本补上这层监管：
  - 子进程退出 ⇒ 记录**退出码与运行时长**，然后**自动重新拉起**；
  - **指数退避** 1s→2s→4s…封顶 30s：避免"起来就崩"把 CPU、日志、MySQL 连接打满；
  - 成功运行 ≥ `STABLE_SECONDS` ⇒ 退避**归零**（偶发崩溃不该背负长期惩罚）；
  - 连续 `MAX_FAST_FAILURES` 次**秒退**（< `FAST_FAIL_SECONDS`）⇒ 更像**配置错误**
    （DSN 配错、端口被占、依赖缺失）而非偶发崩溃 ⇒ **响亮退出**，
    而不是无限刷屏把真正的错误信息淹掉；
  - 拉起前**等端口释放**，避免上一次的 socket 还占着 ⇒ `address already in use` 空转；
  - 收到停止信号 ⇒ 终止子进程并**干净退出，不再重启**。

## 为什么用 `sys.executable` 而非写死解释器

历史坑：`.workbuddy/verify-ui/restart-backend.mjs` 曾写死 uv 的 base python，
那个解释器**没装依赖**（`import uvicorn` 直接 ModuleNotFoundError），拉起来就秒退。
用 `sys.executable` 则**继承启动本脚本的那个解释器** —— 谁把我跑起来，我就用谁跑子进程，
天然避免"监管者用 A 解释器、服务需要 B 解释器"的错配。

## 用法

    cd backend && .venv/Scripts/python.exe -u scripts/serve.py

    # 换一个被监管的目标（自测用：不会拉起第二个真后端 ⇒ 不会出现双份 APScheduler）
    .venv/Scripts/python.exe -u scripts/serve.py --target <某个脚本> --max-restarts 3

## ⚠ 它解决什么、不解决什么

- **解决**：子进程崩溃 / 被单独 `taskkill` / 干净退出 ⇒ 服务自愈。
- **不解决**：把**整棵进程树**一起端掉的外部终止（Windows Job Object 被回收时就是如此）。
  实测本仓库所处的 agent 沙箱：子进程被关在**不允许 breakaway** 的 Job 里，
  detached 子进程会随启动它的那条命令一起死 ⇒ **监管者也会被一起带走**。
  要扛住这类终止，监管者必须活在**沙箱之外**（你自己的终端 / 计划任务 / 容器）。
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKOFF_START = 1.0
BACKOFF_CAP = 30.0
STABLE_SECONDS = 60.0      # 跑够这么久算"稳定"，退避归零
FAST_FAIL_SECONDS = 5.0    # 短于这个算"秒退"
MAX_FAST_FAILURES = 10     # 连续秒退这么多次 ⇒ 判定为配置错误，放弃
PORT_FREE_TIMEOUT = 3.0


def _log(msg: str) -> None:
    """打到 stdout（进后台任务日志）并**立即 flush**。

    ⚠ 必须 flush：本项目踩过『spawn 时没带 -u，Python 重定向到文件块缓冲，
    跑得好好的进程也一字不吐』的坑 —— 观测手段本身失真会把"正常运行"误判成"没起来"。
    """
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [supervisor] {msg}"
    print(line, flush=True)


def _kill_tree(pid: int) -> None:
    """杀掉**整棵进程树**（Windows 用 `taskkill /T /F`）。

    ⚠ 为什么必须杀树，而不是 `Popen.terminate()`：
    `.venv/Scripts/python.exe` 跑脚本时会**再拉一层** —— 实测 `Popen` 拿到的 pid
    与脚本自报的 pid **不同**（如 11116 vs 11240），父链是
    `bash.exe → .venv python → uv 的 python`。既然结构上就是两层，
    只杀直接子进程就等于**赌**"壳死了真身会不会跟着走"（本轮实测会跟着走，但这是运气，不是契约）。
    一旦真身留下，它就继续占着 :8000 ⇒ 下一个实例必然 `address already in use`
    ⇒ 监管者把自己逼进"起来就崩"的死循环。`/T` 连子孙一起带走，把赌运气的部分去掉。
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def _port_in_use(host: str, port: int) -> bool:
    """能 bind 上就说明端口空了（比 connect 更可靠：0.0.0.0 上不一定能 connect）。"""
    probe_host = "" if host in ("0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((probe_host, port))
            return False
        except OSError:
            return True


def _wait_port_free(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_in_use(host, port):
            return True
        time.sleep(0.25)
    return not _port_in_use(host, port)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    ap = argparse.ArgumentParser(description="iterhub 后端监管进程（自愈）")
    ap.add_argument("--target", default=str(script_dir / "run.py"),
                    help="被监管的脚本（默认 scripts/run.py）")
    ap.add_argument("--max-restarts", type=int, default=0,
                    help="最多重启几次后退出；0 = 不限（默认，长期驻留）")
    args = ap.parse_args()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    py = sys.executable
    target = str(Path(args.target).resolve())

    _log(f"监管启动：{py} -u {target}")
    _log(f"目标端口 {host}:{port}；退避 {BACKOFF_START}s→{BACKOFF_CAP}s；"
         f"连续 {MAX_FAST_FAILURES} 次秒退即放弃")

    stopping = False

    def _on_signal(signum, _frame):
        nonlocal stopping
        stopping = True
        _log(f"收到信号 {signum} ⇒ 停止监管，不再重启")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    backoff = BACKOFF_START
    fast_failures = 0
    restarts = 0
    child: subprocess.Popen | None = None

    first_launch = True
    while True:
        # 首次启动**不等待**：此时并不存在"我们自己的上一次"，占着端口的多半是**另一个**实例。
        # 等满超时再启动纯属白等（自测时被这点连拖 3×10s），故首次只做一次**瞬时**检查并按需提示。
        # 只有"我们杀掉/崩掉过一次之后"才值得等 —— 那才是真·残留 socket 的场景。
        if first_launch:
            if _port_in_use(host, port):
                _log(f"ℹ 端口 {host}:{port} 已被占用 —— 可能已有一个实例在跑；"
                     f"仍尝试启动，uvicorn 会自己报错")
            first_launch = False
        elif not _wait_port_free(host, port, PORT_FREE_TIMEOUT):
            _log(f"⚠ 端口 {host}:{port} 在 {PORT_FREE_TIMEOUT}s 内未释放 —— "
                 f"可能另有实例在跑，仍尝试启动（uvicorn 会自己报错）")

        started = time.monotonic()
        # 子进程继承 stdout/stderr ⇒ uvicorn 日志照旧进后台任务日志，可观测性不降级
        child = subprocess.Popen([py, "-u", target], cwd=str(project_root))
        _log(f"已拉起子进程 pid={child.pid}（第 {restarts + 1} 次）")

        # 信号在等待期间也要能打断
        while True:
            try:
                code = child.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if stopping:
                    _log(f"停止中：杀进程树 pid={child.pid}")
                    _kill_tree(child.pid)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        _log("子进程未响应 ⇒ 兜底 kill()")
                        child.kill()
                    return 0

        ran = time.monotonic() - started

        if stopping:
            _log(f"子进程已退出（code={code}），因收到停止信号 ⇒ 不再重启")
            return 0

        _log(f"⚠ 子进程退出：code={code}，运行 {ran:.1f}s")

        if ran < FAST_FAIL_SECONDS:
            fast_failures += 1
            if fast_failures >= MAX_FAST_FAILURES:
                _log(f"⛔ 连续 {fast_failures} 次秒退（每次 < {FAST_FAIL_SECONDS}s）——"
                     f"这更像配置/依赖错误，不是偶发崩溃。放弃监管，请查上面的真实报错。")
                return 1
        else:
            fast_failures = 0
            backoff = BACKOFF_START

        restarts += 1
        if args.max_restarts and restarts >= args.max_restarts:
            _log(f"已达 --max-restarts={args.max_restarts} ⇒ 退出")
            return 0

        if ran >= STABLE_SECONDS:
            backoff = BACKOFF_START

        _log(f"{backoff:.1f}s 后重启（已重启 {restarts} 次，连续秒退 {fast_failures} 次）")
        slept = 0.0
        while slept < backoff and not stopping:
            time.sleep(0.2)
            slept += 0.2
        if stopping:
            _log("停止信号在退避期间到达 ⇒ 退出")
            return 0
        backoff = min(backoff * 2, BACKOFF_CAP)


if __name__ == "__main__":
    sys.exit(main())
