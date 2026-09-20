"""Sprint.issues() 分页回归。

历史缺陷(两份,都会污染报表数据):
1. `jql = jql.format(...)` 把模板原地覆盖 ⇒ 第 2 圈起 startAt 恒为 0,
   表现为「超过一页取不全 + 首页被重复累加」;
2. 非 200 响应既不 break 也不推进 startAt ⇒ 无限循环重打同一地址。

本文件守住三条:分页推进、非 200 抛错、total 虚高时不死循环。
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from util.jira import AuthConfig, Sprint


class FakeResponse:
    def __init__(self, payload=None, status_code=200, reason="OK"):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.reason = reason

    def json(self):
        return self._payload


def _sprint() -> Sprint:
    return Sprint(
        board_id="1",
        board_name="b",
        project_id="P",
        project_name="p",
        sprint_id="9",
        origin_sprint_name="S",
        sprint_name="S",
        short_sprint_name="S",
        startdate=None,
        enddate=None,
        activated_date=None,
        complete_date=None,
        state="closed",
        goal=None,
        auth_config=AuthConfig(user="u", token="t", url="http://rdm.test"),
    )


@pytest.fixture
def no_sleep(monkeypatch):
    """重试里的 time.sleep(2) 在测试里没有意义,直接跳过。"""
    monkeypatch.setattr("util.jira.time.sleep", lambda _s: None)


def _install_get(monkeypatch, handler):
    """handler(url) -> FakeResponse;同时记录每次请求的 URL。"""
    seen: list[str] = []

    def fake_get(url, headers=None, timeout=None):
        seen.append(url)
        return handler(url)

    monkeypatch.setattr("util.jira.requests.get", fake_get)
    return seen


def _page_url_start_ats(seen: list[str]) -> list[str]:
    return [parse_qs(urlparse(u).query)["startAt"][0] for u in seen]


def test_paginates_through_all_pages(monkeypatch, no_sleep):
    """1200 条 ⇒ 三页(0/500/1000),不能重复请求首页。"""
    pages = {0: 500, 500: 500, 1000: 200}

    def handler(url):
        start_at = int(parse_qs(urlparse(url).query)["startAt"][0])
        count = pages.get(start_at, 0)
        return FakeResponse(
            {
                "issues": [{"key": f"ISSUE-{start_at + i}"} for i in range(count)],
                "total": 1200,
            }
        )

    seen = _install_get(monkeypatch, handler)
    issues = _sprint().issues()

    assert _page_url_start_ats(seen) == ["0", "500", "1000"]
    assert len(issues) == 1200
    assert len({i["key"] for i in issues}) == 1200  # 无重复


def test_non_200_raises_instead_of_looping(monkeypatch, no_sleep):
    """非 200 必须抛错;且请求次数有上限(重试 retries=2 ⇒ 共 3 次)。"""
    seen = _install_get(
        monkeypatch,
        lambda url: FakeResponse({}, status_code=500, reason="Server Error"),
    )

    with pytest.raises(RuntimeError, match="HTTP 500"):
        _sprint().issues()

    assert len(seen) == 3  # 1 次 + 2 次重试,不会无限打


def test_stops_when_page_empty_even_if_total_inflated(monkeypatch, no_sleep):
    """total 虚高 + 返回空页时必须停止,不能原地死循环。"""
    calls = {"n": 0}

    def handler(url):
        calls["n"] += 1
        return FakeResponse({"issues": [], "total": 999})

    seen = _install_get(monkeypatch, handler)
    issues = _sprint().issues()

    assert issues == []
    assert calls["n"] == 1  # 空页立即收手
    assert len(seen) == 1
