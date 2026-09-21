"""report_wiki_data 的环境变量契约:凭据缺失即拒绝,内网地址有默认值。"""

import sys

import pytest

_MODULE_PREFIX = "task.report_wiki_data"


def _drop_module() -> None:
    for mod in list(sys.modules):
        if mod.startswith(_MODULE_PREFIX):
            sys.modules.pop(mod, None)


@pytest.fixture(autouse=True)
def _isolate_module():
    """让用例能真正删掉环境变量,并在前后卸载被测模块。

    ⚠ db.database / db.dboperator / api.auth 在**首次 import** 时会调 load_dotenv(),
    而 python-dotenv 默认把 backend/.env 里"缺失"的键灌回 os.environ —— 用例刚
    delenv 掉的 WIKI_* 会在 import task.* 时被 .env 复活,断言就变成取决于
    「执行顺序 + 本地 .env 内容」的薛定谔测试。先导入这三个模块,让 load_dotenv()
    在删变量之前完成。
    """
    import api.auth  # noqa: F401
    import db.database  # noqa: F401
    import db.dboperator  # noqa: F401

    _drop_module()
    yield
    _drop_module()


def test_missing_wiki_credentials_raise(monkeypatch):
    """清空 WIKI_USERNAME / WIKI_PASSWORD 后 import 应当 RuntimeError,而不是悄悄放行。"""
    for k in ("WIKI_USERNAME", "WIKI_PASSWORD", "WIKI_URL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="WIKI_USERNAME"):
        import task.report_wiki_data  # noqa: F401


def test_wiki_url_falls_back_to_default(monkeypatch):
    """WIKI_URL 缺失只该走内置默认值,不该让模块拒绝运行(内网地址不是凭据)。"""
    monkeypatch.delenv("WIKI_URL", raising=False)
    monkeypatch.setenv("WIKI_USERNAME", "u")
    monkeypatch.setenv("WIKI_PASSWORD", "p")
    import task.report_wiki_data as module

    assert module.CONFLUENCE_URL == "http://wiki.zvos.zoomlion.com"


def test_wiki_url_env_overrides_default(monkeypatch):
    """环境变量(.env / deployment.yml)优先于内置默认值。"""
    monkeypatch.setenv("WIKI_URL", "http://wiki.test:8090")
    monkeypatch.setenv("WIKI_USERNAME", "u")
    monkeypatch.setenv("WIKI_PASSWORD", "p")
    import task.report_wiki_data as module

    assert module.CONFLUENCE_URL == "http://wiki.test:8090"
