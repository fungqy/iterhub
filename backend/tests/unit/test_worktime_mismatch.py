"""工时不一致明细接口(迭代概览「工时」卡的下钻)的**行映射与差额口径**。

不打 HTTP:直接 monkeypatch `get_session` 给一个假会话,只验「SQL 结果 → 响应」这一段。
这里有几处非显然、且**漂了界面上看不出来**的口径:

  1. 缺失的一侧(计划或投入为 NULL)按 0 参与差额计算;
  2. 两列在库里是 FLOAT,SQLAlchemy 可能回 Decimal:必须统一成 float,
     否则 Decimal 与 float 混算直接抛 TypeError、FastAPI 也无法序列化 Decimal;
  3. ⚠⚠ **清单必须两个方向都列**(用户 2026-09-17 报过「明细里的差额与卡片上的对不上」)。
     起初只列了「投入 > 计划」的方向,清单里差额列相加(实测 botadp-Sprint-11 = +28)
     必然大于整迭代净差额(+8) —— 欠报那部分被丢掉了。
     全列之后这条恒等式成立,且它是本弹窗**唯一**的对账手段(没有合计行、没有说明文字):
         sum(rows[*].delta) == delta_total
     故下面把它写成断言 —— 谁把清单过滤回单方向,这条就红。
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from api.routes import reports as rp

SPRINT_ID = 8354  # botadp-Sprint-11


class _FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeSession:
    """只认这句接口发的两条 SQL:合计(SUM)与明细(ORDER BY)。多发的会直接抛错。"""

    def __init__(self, totals: tuple[Any, ...], rows: list[Any]):
        self.totals = totals
        self.rows = rows

    def execute(self, stmt, params=None):  # noqa: ANN001
        sql = str(stmt)
        if "ORDER BY" in sql:
            return _FakeResult(self.rows)
        assert "SUM(plan_worktime)" in sql, f"未预期的查询: {sql[:120]}"
        return _FakeResult([self.totals])

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any):
        return False


def _run(monkeypatch, totals, rows):
    monkeypatch.setattr(rp, "get_session", lambda: _FakeSession(totals, rows))
    return asyncio.run(rp.get_worktime_mismatch(SPRINT_ID, current_user={}))


#: 前三条是 2026-09-17 对 botadp-Sprint-11 的**实测**超支条目(+16 +8 +4 = +28);
#: 第四条是欠报那一侧的**代表行**(−20):真库那边是 71 行合计 −20,这里用一行代替,
#: 好让四条之和恰好等于净差额 +8 —— 与此前"清单只列超支方向"的 bug 形成对照。
TOTALS = (Decimal("482.0"), Decimal("490.0"))
ROWS = [
    ("EMBODIED_ADP-3603", "插件和机器人CLI统一：远程控制终端", "任务",
     "李昊", "已完成", Decimal("8.0"), Decimal("24.0")),
    ("EMBODIED_ADP-3570", "时间轴-调试面板-语音对话优化交互事件", "子任务",
     "魏忠亮", "已完成", Decimal("8.0"), Decimal("16.0")),
    ("EMBODIED_ADP-3581", "卡片UI设计", "子任务", "石燕兵", "已完成",
     Decimal("4.0"), Decimal("8.0")),
    # ⚠ 反方向:计划有、投入漏填 ⇒ 负差额,必须也在清单里
    ("EMBODIED_ADP-3500", "插件和机器人CLI统一：指令下发", "子任务",
     "李昊", "已完成", Decimal("28.0"), Decimal("8.0")),
]


def test_maps_rows_and_keeps_both_directions(monkeypatch):
    res = _run(monkeypatch, TOTALS, ROWS)

    assert res["sprint_id"] == SPRINT_ID
    # 整迭代合计与净差额(卡片口径):490 − 482 = +8
    assert res["plan_total"] == 482.0
    assert res["actual_total"] == 490.0
    assert res["delta_total"] == 8.0

    first, second, third, fourth = res["rows"]
    assert isinstance(first["plan_worktime"], float), "Decimal 必须转成 float"
    assert (first["delta"], second["delta"], third["delta"]) == (16.0, 8.0, 4.0)
    # 负差额行也在清单里,且符号保留(不是取绝对值)
    assert fourth["delta"] == -20.0
    assert fourth["plan_worktime"] == 28.0 and fourth["actual_worktime"] == 8.0

    # ⚠ 核心不变量:清单自带的对账。没有合计行、没有说明文字,全靠这条成立。
    assert round(sum(r["delta"] for r in res["rows"]), 2) == res["delta_total"]

    # 响应形状(刻意很薄):UI 只用 rows,合计三兄弟是给这条断言用的
    assert set(res.keys()) == {"sprint_id", "plan_total", "actual_total", "delta_total", "rows"}


def test_missing_side_counts_as_zero(monkeypatch):
    """缺失的一侧按 0 参与差额:计划漏填 ⇒ 差额 = +投入;投入漏填 ⇒ 差额 = −计划。

    ⚠ 两条都必须是清单里的条目(它们都算"不一致"),而且 plan/actual 本身仍回 null,
      留给前端显示占位「—」—— 只有差额里的 0 是替代值,不能把 null 直接改成 0 回吐。
    """
    totals = (Decimal("0.0"), Decimal("16.0"))
    rows = [
        ("EMBODIED_ADP-4001", "计划漏填但有投入", "子任务", "张三", "已完成", None, Decimal("16.0")),
    ]
    res = _run(monkeypatch, totals, rows)
    row = res["rows"][0]
    assert row["plan_worktime"] is None and row["delta"] == 16.0

    totals = (Decimal("16.0"), Decimal("0.0"))
    rows = [
        ("EMBODIED_ADP-4002", "投入漏填", "子任务", "李四", "已完成", Decimal("16.0"), None),
    ]
    res = _run(monkeypatch, totals, rows)
    row = res["rows"][0]
    assert row["actual_worktime"] is None and row["delta"] == -16.0
    assert round(sum(r["delta"] for r in res["rows"]), 2) == res["delta_total"] == -16.0


def test_unsynced_sprint_keeps_nulls(monkeypatch):
    """两列全 NULL(该映射上线前同步的 Sprint):合计与净差额都是 null,不能兜成 0。

    兜成 0 会让「未接入工时」的迭代看起来像「计划 0 小时、投入 0 小时、正好吻合」。
    """
    res = _run(monkeypatch, (None, None), [])
    assert res["plan_total"] is None
    assert res["actual_total"] is None
    assert res["delta_total"] is None
    assert res["rows"] == []
