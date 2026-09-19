"""JWT SECRET_KEY 解析策略

⚠⚠ **本文件刻意不再 `importlib.reload(api.auth)`**(2026-09-17 改)。

为什么不用 reload:`reload` 会**替换 `api.auth` 的模块对象**,而 `api.routes.*` 在导入时
已经把 `get_current_user_from_header` 绑定到了旧函数对象上。之后测试里
`app.dependency_overrides[get_current_user_from_header]` 拿到的可能是重载后的新对象,
它与路由 `Depends(...)` 持有的旧对象**不是同一个函数** ⇒ 覆盖失效、鉴权回落到真实 JWT
校验,表现为「单独跑绿、按某种顺序一起跑就 401」。实测复现:
`pytest tests/unit/test_jwt_secret.py tests/api/test_scheduler_routes.py`。

改为直接调用被测的纯函数 `_resolve_jwt_secret()`:它与模块导入时的解析逻辑完全相同
(模块级 `SECRET_KEY = _resolve_jwt_secret()`),但不改动模块对象与模块级状态,
因此不会污染其它用例。

唯一仍需隔离的是 `dotenv.load_dotenv`:它在 `api.auth` 模块顶层把 backend/.env 里的
`JWT_SECRET_KEY` 灌进 `os.environ`,会让 `monkeypatch.delenv` 形同虚设(清空后照样能被
填回来)。本文件用 autouse fixture 把它 patch 掉;因为不再 reload,用例结束后也无需
做任何还原。
"""

from unittest.mock import patch

import pytest

from api import auth as auth_module


@pytest.fixture(autouse=True)
def _isolate_dotenv():
    """屏蔽 .env 注入,保证解析结果只取决于 monkeypatch 设的环境变量。"""
    with patch("dotenv.load_dotenv", lambda *a, **k: None):
        yield


def test_placeholder_secret_raises(monkeypatch):
    """占位符默认值必须被拒绝,不能悄悄放行(模块导入时即会抛出)。"""
    monkeypatch.setenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
    with pytest.raises(RuntimeError, match="占位符"):
        auth_module._resolve_jwt_secret()


def test_unset_secret_generates_random(caplog, monkeypatch):
    """未设置时必须生成随机 key + 打 WARNING,而非用占位符放行。"""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with caplog.at_level("WARNING", logger="Auth"):
        key = auth_module._resolve_jwt_secret()

    assert key
    assert key != "your-secret-key-change-in-production"
    # 长度是"确实是新生成的"的旁证:.env 里那个 key 是 152 字符
    assert len(key) != 152
    assert any("未设置" in r.message for r in caplog.records), (
        "没收到 WARNING —— 检查是不是被 .env 的 JWT_SECRET_KEY 顶掉了"
    )


def test_real_secret_accepted(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "my-real-secret-12345")
    assert auth_module._resolve_jwt_secret() == "my-real-secret-12345"


def test_create_and_decode_token_roundtrip():
    """端到端:签发 → 解码 → payload 还原"""
    token = auth_module.create_access_token({"sub": "1", "username": "alice"})
    payload = auth_module.decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "1"
    assert payload["username"] == "alice"
