"""统一异常→HTTP 错误分类

设计目标:
- 把 requests/SQL/IO 等典型异常归类为面向用户的友好中文消息
- 只暴露根因 + 短摘要,绝不泄露 token、内部堆栈、完整 URL
- 给上层 (FastAPI 全局 handler) 装配一个统一的错误出口
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger("GlobalError")


def _extract_host(msg: str) -> str:
    """从 requests ConnectionError 字符串中解析 host"""
    if "host='" in msg:
        return msg.split("host='", 1)[1].split("'", 1)[0]
    return ""


def _root_cause(e: BaseException) -> BaseException:
    """沿 __cause__/__context__ 链找到最底层的异常"""
    seen: set[int] = {id(e)}
    cur: BaseException = e
    while True:
        nxt = cur.__cause__ or cur.__context__
        if nxt is None or id(nxt) in seen:
            return cur
        seen.add(id(nxt))
        cur = nxt


def classify_error(e: Exception) -> tuple[int, str]:
    """把任意异常归类为 (http_status_code, 用户可见错误描述)。

    - requests.exceptions.ConnectionError(包含 NameResolutionError)
        → 502 Bad Gateway + "无法解析域名 <host>" 或 "无法连接 <host>"
    - requests.exceptions.Timeout → 504 Gateway Timeout
    - requests.exceptions.HTTPError(4xx/5xx) → 502 Bad Gateway + "上游返回 HTTP <code>"
    - requests.exceptions.SSLError → 502 Bad Gateway + SSL 摘要
    - 其他 requests.RequestException → 502 Bad Gateway
    - 其余 Exception → 500 + "<异常类型>: <前 200 字符>"

    返回的消息长度不超过 200 字符,不会泄露 token / 完整堆栈。
    """
    msg = str(e) or ""

    if isinstance(e, requests.exceptions.SSLError):
        return 502, f"SSL 连接失败: {str(_root_cause(e))[:200]}"
    if isinstance(e, requests.exceptions.Timeout):
        return 504, "请求超时,请稍后重试"
    if isinstance(e, requests.exceptions.ConnectionError):
        host = _extract_host(msg)
        if (
            "Name or service not known" in msg
            or "Failed to resolve" in msg
            or "NameResolutionError" in msg
        ):
            target = host or "目标服务"
            return 502, f"无法解析域名 {target},请检查网络或 DNS 配置"
        if "Connection refused" in msg:
            return 502, f"连接被拒绝 {host}:80,请确认服务已启动"
        if "timed out" in msg.lower():
            return 504, f"连接 {host} 超时"
        target = host or "目标服务"
        return 502, f"无法连接 {target}: {msg[:200]}"
    if isinstance(e, requests.exceptions.HTTPError):
        code = e.response.status_code if e.response is not None else "?"
        body = ""
        if e.response is not None and e.response.text:
            body = e.response.text[:200]
        if body:
            return 502, f"上游返回 HTTP {code}: {body}"
        return 502, f"上游返回 HTTP {code}"
    if isinstance(e, requests.exceptions.RequestException):
        return 502, f"上游请求失败: {str(e)[:200]}"

    # 非 requests 异常:仅给类型 + 短消息,绝不附堆栈
    short = msg[:200] if msg else "(无详细信息)"
    return 500, f"{type(e).__name__}: {short}"


def install_exception_handler(app) -> None:
    """在 FastAPI app 上挂载全局 Exception handler。

    行为约定:
    - 仅兜底未捕获的异常;已通过 HTTPException 显式抛出的错误仍走 FastAPI 默认流程
    - 日志只输出 [METHOD PATH] + 友好消息,**不输出完整 traceback**
    - 返回 JSON { "detail": "..." }
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def handler(request: Request, exc: Exception):
        # FastAPI 自带的 HTTPException / RequestValidationError 由
        # 它们自己的 handler 接管,这里只处理其余异常。
        from fastapi import HTTPException
        from fastapi.exceptions import RequestValidationError

        if isinstance(exc, (HTTPException, RequestValidationError)):
            # 理论上不会走到这里(add_exception_handler 不会覆盖这两类)
            # 兜底直接交还,避免行为不一致
            raise exc

        status, friendly = classify_error(exc)
        logger.error("[%s %s] %s", request.method, request.url.path, friendly)
        return JSONResponse(status_code=status, content={"detail": friendly})

    app.add_exception_handler(Exception, handler)
