"""「未被用例覆盖的故事」列表接口的**筛选口径与行映射**(概览「用例覆盖率」卡的下钻)。

为什么单独钉:它与 /sprint-summary 的 case_uncovered_story_count 是一对**互补口径**
(NOT EXISTS 取 INNER JOIN 的补集),卡片上的「未覆盖 N」与这里列出的行数必须逐条对得上。
两处判定分散在两个接口里,谁改了单侧都不会报错,界面上只表现为「列表比数字多/少几条」,
极难发现 —— 故把三条关键约束写成断言。

不打 HTTP:直接 monkeypatch `get_session` 给一个假会话,只验「SQL 口径 → 响应」这一段。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from api.routes import reports as rp

SPRINT_ID = 8068  # botadp-Sprint-9


class _FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """只认这一句查询:记录 SQL 与参数供断言。"""

    def __init__(self, rows: list[Any]):
        self.rows = rows
        self.sql = ""
        self.params: dict = {}

    def execute(self, stmt, params=None):  # noqa: ANN001
        self.sql = str(stmt)
        self.params = dict(params or {})
        return _FakeResult(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any):
        return False


def _run(monkeypatch, rows):
    session = _FakeSession(rows)
    monkeypatch.setattr(rp, "get_session", lambda: session)
    result = asyncio.run(rp.get_case_uncovered_stories(SPRINT_ID, current_user={}))
    return session, result


def test_scopes_to_sprint_stories_and_excludes_covered(monkeypatch):
    session, _ = _run(monkeypatch, [])

    # 故事口径必须与 /sprint-summary 的「故事数」分母逐字一致,否则覆盖率对不上计数
    assert "issue_type IN ('故事', '简单故事')" in session.sql
    assert "i.sprint_id = :sprint_id" in session.sql
    assert session.params == {"sprint_id": SPRINT_ID}

    # 补集写成 NOT EXISTS,且只按 story_key 关联(覆盖率那边是 INNER JOIN 同一列)
    assert "NOT EXISTS" in session.sql
    assert "rdm_testcase" in session.sql
    assert "t.story_key = i.issue_key" in session.sql

    # ⚠ rdm_testcase 侧**不能**再加 sprint_id 条件:故事从 A 迭代挪到 B 迭代时,
    #   用例行的 sprint_id 会停在导入当时解析出的迭代,带上它会把 B 迭代里
    #   确实被覆盖的故事误判成「未覆盖」(与 /sprint-summary 的覆盖率口径同源)。
    assert "t.sprint_id" not in session.sql


def test_nullable_columns_are_defaulted(monkeypatch):
    """priority / assignee 的「非空」由 SQL 的 COALESCE 保证 —— 与 /unplanned-stories 逐字同款。

    这里断言 SQL 里有 COALESCE(而不是在 Python 侧再兜一次):两个接口必须同表同投影,
    谁少兜一层,两处列表在同一条数据上就会显示成 '' 与 None 两种样子。
    """
    session, _ = _run(monkeypatch, [])
    assert "COALESCE(i.priority, '')" in session.sql
    assert "COALESCE(i.assignee, '')" in session.sql


def test_maps_rows_to_story_list_shape(monkeypatch):
    """行结构与 /unplanned-stories 完全一致(前端两张列表共用同一个弹窗)。"""
    created = datetime(2026, 8, 3, 14, 25, 30)
    _, result = _run(monkeypatch, [
        ("botadp-123", "故事甲", "处理中", "严重", "张三", created),
        # 名称 / 状态在库里是 NULL 时兜成空串;created 保持 None(前端显示「—」)
        ("botadp-456", None, None, "", "", None),
    ])

    assert result == [
        {
            "issue_key": "botadp-123",
            "issue_name": "故事甲",
            "status": "处理中",
            "priority": "严重",
            "assignee": "张三",
            "created": "2026-08-03 14:25:30",
        },
        {
            "issue_key": "botadp-456",
            "issue_name": "",
            "status": "",
            "priority": "",
            "assignee": "",
            "created": None,
        },
    ]
