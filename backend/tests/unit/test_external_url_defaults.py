"""remind_sonar_scan 的环境变量契约:凭据缺失即拒绝,内网地址有默认值。

默认值取自 .env.example(内网地址不是凭据),环境变量仍可覆盖。
"""

import sys

import pytest

_MODULE_PREFIX = "task.remind_sonar_scan"

_CREDENTIALS = {
    "GITLAB_TOKEN": "t",
    "GITLAB_USERNAME": "u",
    "SONAR_TOKEN": "s",
}


def _drop_module() -> None:
    for mod in list(sys.modules):
        if mod.startswith(_MODULE_PREFIX):
            sys.modules.pop(mod, None)


@pytest.fixture(autouse=True)
def _isolate_module():
    """让用例能真正删掉环境变量,并在前后卸载被测模块。

    ⚠ db.database / db.dboperator / api.auth 在**首次 import** 时会调 load_dotenv(),
    而 python-dotenv 默认把 backend/.env 里"缺失"的键灌回 os.environ —— 用例刚
    delenv 掉的 GITLAB_URL / SONAR_URL 会在 import task.* 时被 .env 复活,断言就变成
    取决于「执行顺序 + 本地 .env 内容」的薛定谔测试。先导入这三个模块,让
    load_dotenv() 在删变量之前完成。
    """
    import api.auth  # noqa: F401
    import db.database  # noqa: F401
    import db.dboperator  # noqa: F401

    _drop_module()
    yield
    _drop_module()


def _set_credentials(monkeypatch) -> None:
    for key, value in _CREDENTIALS.items():
        monkeypatch.setenv(key, value)


def test_missing_sonar_credentials_raise(monkeypatch):
    """凭据缺失时 import 应当 RuntimeError,而不是悄悄放行。"""
    for key in (*_CREDENTIALS, "GITLAB_URL", "SONAR_URL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="GITLAB_TOKEN"):
        import task.remind_sonar_scan  # noqa: F401


def test_urls_fall_back_to_defaults(monkeypatch):
    """GITLAB_URL / SONAR_URL 缺失只该走内置默认值,不该让任务模块拒绝运行。"""
    monkeypatch.delenv("GITLAB_URL", raising=False)
    monkeypatch.delenv("SONAR_URL", raising=False)
    _set_credentials(monkeypatch)
    import task.remind_sonar_scan as module

    assert module.GITLAB_URL == "http://gitlab.zoomlion.com"
    assert module.SONAR_URL == "http://sonar.zvos.zoomlion.com"
    # 派生出来的接口地址也要跟着默认值走
    assert module.PROJECTS_API == "http://sonar.zvos.zoomlion.com/api/projects/search"


def test_url_env_overrides_default(monkeypatch):
    """环境变量(.env / deployment.yml)优先于内置默认值。"""
    _set_credentials(monkeypatch)
    monkeypatch.setenv("GITLAB_URL", "http://gitlab.test:8080")
    monkeypatch.setenv("SONAR_URL", "http://sonar.test:9000")
    import task.remind_sonar_scan as module

    assert module.GITLAB_URL == "http://gitlab.test:8080"
    assert module.SONAR_URL == "http://sonar.test:9000"
