"""FastAPI 全局 Exception handler 行为测试"""

import logging

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from util.errors import install_exception_handler

DNS_ERR_STR = (
    "HTTPConnectionPool(host='rdm.zvos.zoomlion.com', port=80): "
    "Max retries exceeded with url: /rest/agile/1.0/board/1044/sprint?state=active "
    "(Caused by NameResolutionError(\"<urllib3.connection.HTTPConnection object>: "
    "Failed to resolve 'rdm.zvos.zoomlion.com' "
    "([Errno -2] Name or service not known)\"))"
)


def _build_app_with_route(raiser):
    """构造一个最小 FastAPI app,挂载会抛 raiser() 的 GET 路由。"""
    app = FastAPI()
    install_exception_handler(app)

    @app.get("/boom")
    def boom():
        raiser()
        return {"ok": True}

    return app


def test_connection_error_dns_returns_502_with_friendly_message(caplog):
    def raise_dns():
        raise requests.exceptions.ConnectionError(DNS_ERR_STR)

    app = _build_app_with_route(raise_dns)

    with caplog.at_level(logging.ERROR, logger="GlobalError"):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/boom")

    assert resp.status_code == 502
    body = resp.json()
    assert "rdm.zvos.zoomlion.com" in body["detail"]
    assert "无法解析域名" in body["detail"]

    # 关键回归:日志里只应有 1 条 ERROR,不输出 traceback
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "Traceback" not in error_records[0].getMessage()
    assert "/boom" in error_records[0].getMessage()


def test_unexpected_exception_returns_500_short_message(caplog):
    def raise_value_error():
        raise ValueError("bad input")

    app = _build_app_with_route(raise_value_error)

    with caplog.at_level(logging.ERROR, logger="GlobalError"):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/boom")

    assert resp.status_code == 500
    assert "ValueError" in resp.json()["detail"]
    assert "bad input" in resp.json()["detail"]
    assert "Traceback" not in caplog.records[0].getMessage()


def test_http_exception_passes_through_untouched():
    """FastAPI 自带的 HTTPException 不应被全局 handler 改写。"""
    from fastapi import HTTPException

    def raise_http():
        raise HTTPException(status_code=404, detail="项目不存在")

    app = _build_app_with_route(raise_http)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "项目不存在"
