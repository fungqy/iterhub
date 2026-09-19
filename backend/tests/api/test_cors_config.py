"""CORS 配置回归:不允许 origins=* + credentials=True 这种禁用组合"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _cors_middleware(app: FastAPI):
    """返回应用上挂载的 CORS 中间件实例"""
    for m in app.user_middleware:
        if m.cls is CORSMiddleware:
            return m
    raise AssertionError("未挂载 CORSMiddleware")


def test_cors_does_not_combine_wildcard_with_credentials():
    """CORS 规范禁止 allow_origins=['*'] 与 allow_credentials=True 同时出现。"""
    from api.main import app

    m = _cors_middleware(app)
    opts = m.kwargs
    assert opts.get("allow_credentials") is False, (
        "allow_credentials=True 配合 wildcard origin 是非法/危险的组合,"
        "应改为 False(JWT 用 Authorization header 不需要 cookie)"
    )
    assert opts.get("allow_origins") == ["*"]


def test_preflight_response_succeeds():
    """OPTIONS 预检请求应能正常返回,不被中间件拒掉。"""
    from api.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.options(
        "/",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in (200, 405)
    # 关键:中间件应放行,Access-Control-Allow-Origin 头应出现
    assert "access-control-allow-origin" in {k.lower() for k in resp.headers}
