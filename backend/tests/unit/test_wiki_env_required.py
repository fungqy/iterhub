"""report_wiki_data 缺失 WIKI_* 环境变量时,模块导入即拒绝。"""

import pytest


def test_missing_wiki_env_raises(monkeypatch):
    """清空 WIKI_USERNAME 后 import 应当 RuntimeError,而不是悄悄放行。"""
    for k in ("WIKI_USERNAME", "WIKI_PASSWORD", "WIKI_URL"):
        monkeypatch.delenv(k, raising=False)
    # 把已加载的模块清掉,让 import 重新走一遍
    import sys
    for mod in list(sys.modules):
        if mod.startswith("task.report_wiki_data"):
            sys.modules.pop(mod, None)
    with pytest.raises(RuntimeError, match="WIKI_USERNAME"):
        import task.report_wiki_data  # noqa: F401
