"""文档故障「导入前校验」:行级必填、故事号解析、与导入的同源性。

不依赖真实 MySQL —— session 用假的(只回两句固定 SQL 的结果),判定逻辑本身
是纯函数。这样测的是**口径**而不是环境,任何一条挂掉都指向"用户看到的校验
结论不对",而不是"本机没装 MySQL"。
"""

from __future__ import annotations

from typing import Any

import pytest

from api.routes import data_import as di
from api.routes.data_import import (
    REQUIRED_ROW_FIELDS,
    build_doc_bug_row,
    evaluate_doc_bug_rows,
    looks_like_story_suffix,
    normalize_sprint_name,
    resolve_story_key,
)

# ── 伪造 session ────────────────────────────────────────────
# evaluate_doc_bug_rows 只发两种查询:_load_sprint_map 与 _load_story_index。
# 按 SQL 里的关键词分流,免得为两个表各写一套 mock 链。
SPRINTS = [
    # (sprint_id, sprint_name, project_id)
    ("8354", "botadp-Sprint-11", "13710"),
    # 2026-09-19 新增:与 8354 **同项目**的另一个迭代。测「按迭代收窄」必须有这样一个
    # 迭代 —— 用 8355 测不出来,它属别的项目,会在更早的项目判定就被拦下。
    ("8356", "botadp-Sprint-12", "13710"),
    ("8355", "RobotClaw-Sprint 2", "13899"),   # ⚠ 库里无空格,故意留空格测归一化
    ("9001", "其他项目迭代", "99999"),
]

ISSUES = [
    # (issue_key, sprint_id)
    ("EMBODIED_ADP-4068", "8354"),   # 正常命中
    ("EMBODIED_ADP-113", "8354"),    # 后缀撞车组之一(同 sprint)
    ("ROBOTCLAW-113", "8355"),       # 同后缀不同 sprint
    ("CMP-113", "9001"),             # 同后缀第三个 sprint
    ("JSST-77", "8355"),
    ("JSST-77", "8354"),             # ⚠ 同后缀在两个 sprint 各一条
    ("JSST-77", "8354"),             # ⚠ 同一 sprint 内重复 ⇒ 真歧义
    ("MOWING-999", "8354"),
]


class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeSession:
    """只认两句 SELECT 的假 session。多发的查询会直接抛错,避免静默绕过。"""

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "FROM rdm_issue" in sql:
            return _Rows(ISSUES)
        if "FROM rdm_sprint" in sql:
            return _Rows(SPRINTS)
        raise AssertionError(f"未预期的查询: {sql[:120]}")


@pytest.fixture
def session():
    return FakeSession()


def _story_index() -> dict[str, list[tuple[str, str]]]:
    """倒排索引的真身 —— 与 evaluate 内部调的是同一个函数。"""
    return di._load_story_index(FakeSession())


# 表头:按 COLUMN_ALIASES 的真实列名建,顺序随意(靠 find_column_index 定位)
HEADERS = [
    "自动编号", "优先级", "处理人", "处理状态", "问题详述",
    "sprint", "故事号", "问题类别",
]


def make_row(**overrides: str) -> list[str]:
    """按 HEADERS 顺序造一行,默认全填合法值。"""
    base = {
        "自动编号": "m0911001",
        "优先级": "中",
        "处理人": "张三",
        "处理状态": "已解决",
        "问题详述": "点不动",
        "sprint": "botadp-Sprint-11",
        "故事号": "4068",
        "问题类别": "代码问题",
    }
    base.update(overrides)
    values = [base[h] for h in HEADERS]
    return values


# ══ 故事号形态 ══════════════════════════════════════════════
class TestStorySuffixForm:
    @pytest.mark.parametrize("raw", ["4068", " 4068 ", "113"])
    def test_accepts_pure_number(self, raw):
        assert looks_like_story_suffix(raw) is True

    @pytest.mark.parametrize(
        "raw",
        ["EMBODIED_ADP-4068", "4068-", "ADP4068", "4068时", "", "  "],
    )
    def test_rejects_anything_else(self, raw):
        """填完整 key 也判错 —— 库里存的是纯数字,与其猜意图不如亮出期望形态。"""
        assert looks_like_story_suffix(raw) is False


class TestResolveStoryKey:
    """三步:形态 → 存在 → 与本行 sprint 对应。"""

    @pytest.fixture(autouse=True)
    def _index(self):
        self.index = di._load_story_index(FakeSession())

    def test_happy_path_returns_full_key(self, _index=None):
        key, err = resolve_story_key("4068", "8354", self.index)
        assert (key, err) == ("EMBODIED_ADP-4068", None)

    def test_disambiguates_by_sprint(self):
        """`113` 横跨三个 sprint ⇒ 只有本行 sprint 的那一个才认。"""
        assert resolve_story_key("113", "8355", self.index)[0] == "ROBOTCLAW-113"
        assert resolve_story_key("113", "9001", self.index)[0] == "CMP-113"

    def test_empty_rejected(self):
        key, err = resolve_story_key("  ", "8354", self.index)
        assert key is None and "为空" in err

    def test_wrong_form_reports_expected_shape(self):
        key, err = resolve_story_key("EMBODIED_ADP-4068", "8354", self.index)
        assert key is None
        assert "纯数字" in err and "4068" in err

    def test_unknown_suffix_reports_not_found(self):
        key, err = resolve_story_key("999999", "8354", self.index)
        assert key is None and "找不到" in err

    def test_suffix_in_other_sprint_reports_mismatch(self):
        """`999` 只在 8354,拿 8355 问就该说"与本行 sprint 不一致"。"""
        key, err = resolve_story_key("999", "8355", self.index)
        assert key is None
        assert "不一致" in err and "8354" in err

    def test_ambiguous_within_same_sprint_lists_candidates(self):
        """`77` 在 8354 下有两条 ⇒ 不能瞎选一个,列出候选让人去 RDM 核。"""
        key, err = resolve_story_key("77", "8354", self.index)
        assert key is None
        assert "多个故事" in err and "JSST-77" in err

    def test_same_suffix_different_sprints_is_not_ambiguous(self):
        """撞车本身不是错误 —— 按 sprint 求交后唯一即可。这是本次口径的核心。"""
        assert resolve_story_key("113", "8354", self.index)[1] is None


# ══ 行级必填 ════════════════════════════════════════════════
class TestRequiredRowFields:
    def _cols(self):
        return {f: di.find_column_index(HEADERS, a) for f, a in di.COLUMN_ALIASES.items()}

    def _build(self, values):
        # ⚠ 必须给**真索引**,不能给 `{}` —— 空字典仍算 strict(按 `is not None` 判定),
        # 于是任何故事号都会报"找不到"。这个坑我自己踩过:用例红了半轮才发现
        # 是 fixture 写错了,而不是产品代码错了。
        return build_doc_bug_row(
            values, self._cols(), story_index=_story_index(), sprint_id="8354"
        )

    @pytest.mark.parametrize("field", list(REQUIRED_ROW_FIELDS.keys()))
    def test_each_required_field_blocks_when_empty(self, field):
        label = REQUIRED_ROW_FIELDS[field]
        row, err = self._build(make_row(**{label: ""}))
        assert row is None, f"{label} 为空却放过了"
        assert err == f"[{label}]为空"

    def test_whitespace_only_counts_as_empty(self):
        """⚠ 回归钉:源表那 27 行【问题详述】原文是 `" "`。

        按原值判 `not " "` ⇒ False ⇒ 算填了,而写库时 cell_text() 会 strip ——
        用户会看到"校验通过"却在库里看到空值。空值判定必须走 strip 后的值。
        """
        row, err = self._build(make_row(优先级="   "))
        assert row is None and err == "[优先级]为空"

    def test_all_filled_passes(self):
        row, err = self._build(make_row())
        assert err is None
        # 故事号 2026-09-18 起不再做严格校验 ⇒ 原值透传(不再是解析后的 issue_key)
        assert row["key"] == "m0911001" and row["story_key"] == "4068"

    def test_error_order_follows_declaration(self):
        """多个字段同时为空时报**声明顺序里的第一个**,报错才稳定可预期。

        ⚠ 故事号 2026-09-18 起不在 REQUIRED_ROW_FIELDS,改用剩余 6 个必填列里的
          几个构造"多个同时为空"以便继续测声明顺序的稳定性。
        """
        values = make_row(优先级="", 处理人="", 处理状态="")
        _, err = self._build(values)
        assert err == "[优先级]为空"


class TestLenientPathUnchanged:
    """不给 story_index ⇒ 保持改版前口径。这些断言守着"导入侧不新增拦截"。"""

    def _cols(self):
        return {f: di.find_column_index(HEADERS, a) for f, a in di.COLUMN_ALIASES.items()}

    def test_story_key_passes_through_raw(self):
        row, err = build_doc_bug_row(
            make_row(故事号=""), self._cols(), story_index=None, sprint_id=None
        )
        assert err is None                     # 空故事号不拦
        assert row["story_key"] == ""          # 原值直通,不做解析

    def test_lenient_still_checks_key_and_desc(self):
        _, err = build_doc_bug_row(make_row(自动编号=""), self._cols())
        assert err == "[自动编号]为空"

    def test_whitespace_desc_is_filled_on_lenient_side(self):
        """宽松侧判详述用的是 strip 后的值 ⇒ `" "` 也算**空**,会被拦。

        这正是改版前的行为(那时候 desc_val 就已经 strip 过),别把它当成新拦截。
        """
        _, err = build_doc_bug_row(make_row(问题详述=" "), self._cols())
        assert err == "[问题详述]为空"


# ══ 整表评估:与导入同源 ════════════════════════════════════
class TestEvaluateRows:
    def test_other_project_rows_skipped_before_field_check(self, session):
        """⚠ 判定的**顺序**有语义:先按 sprint 排除异项目行,再校验字段。

        反过来的话,一份含多项目行的表会把异项目行也报成"[必填列]为空",
        而用户根本不该为那些行负责(换个项目再导即可)。
        """
        rows = [
            (2, make_row(sprint="其他项目迭代", 故事号="")),   # 异项目:应静默跳过
            (3, make_row()),                                    # 有效
        ]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["ok"] is True
        assert ev["importable"] == 1
        assert ev["skipped"]["other_project"] == 1
        assert ev["invalid_detail"] == {}          # 未被误报成字段问题
        assert ev["errors"] == []

    def test_no_sprint_rows_are_out_of_scope(self, session):
        rows = [(2, make_row(sprint="")), (3, make_row())]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["skipped"]["no_sprint"] == 1
        assert ev["importable"] == 1               # 不计入 invalid

    def test_unknown_sprint_reported_separately(self, session):
        """「名字拼错」和「属于别的项目」必须是两类原因 —— 前者要改表,后者换项目即可。"""
        rows = [(2, make_row(sprint="压根不存在的迭代"))]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["skipped"]["unknown_sprint"] == 1
        assert ev["skipped"]["other_project"] == 0
        assert "匹配不到同名迭代" in ev["skipped_by_sprint"]["压根不存在的迭代"]["reason"]

    def test_sprint_name_normalized(self, session):
        """表里写的名字与库里不同(空格/连字符/大小写)也要匹配上。"""
        rows = [(2, make_row(sprint="BOTADP-sprint11"))]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["importable"] == 1
        assert ev["valid_rows"][0]["sprint_id"] == "8354"

    def test_invalid_detail_aggregates_by_field(self, session):
        """逐条清单会被 MAX_REPORTED_ERRORS 截断,聚合计数才是"还剩多少行"的依据。

        ⚠ 故事号 2026-09-18 起两路径都通过,改用其它必填列造"同类问题聚类"。
        """
        rows = [
            (2, make_row(优先级="")),
            (3, make_row(优先级="")),
            (4, make_row(处理状态="")),
        ]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["invalid_detail"] == {"优先级": 2, "处理状态": 1}
        assert ev["skipped"]["invalid"] == 3

    def test_errors_carry_sheet_row_numbers(self, session):
        # ⚠ 故事号 2026-09-18 起两路径都通过,改用「优先级」做"行号挂钩"的样例
        rows = [(7, make_row(优先级="")), (8, make_row())]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["errors"] == ["第7行: [优先级]为空"]

    def test_missing_header_fails_batch(self, session):
        """列级校验:表头缺列是整批不可用,与逐行问题不同级。"""
        headers = [h for h in HEADERS if h != "sprint"]
        ev = evaluate_doc_bug_rows(session, headers, [(2, make_row())], "13710", strict=True)
        assert ev["ok"] is False
        assert ev["importable"] == 0
        assert "sprint" in ev["errors"][0]

    def test_strict_and_lenient_share_processable_scope(self, session):
        """同源性钉子:strict 判定通过的行,宽松口径也必须通过。

        反过来不成立(严格是宽松的真子集)—— 若这条挂了,说明两条路径
        在"哪些行属于本次范围"上已经分叉,"校验说能导、真导却不认"就会复发。

        ⚠ 故事号 2026-09-18 起两路径都放过,这里改用「处理状态」造严格拦、宽松放的差异
          (原用例里的 make_row(故事号="") 现在两侧都放过)。
        """
        rows = [
            (2, make_row()),                                   # 合法
            (3, make_row(处理状态="")),                        # 严格拦、宽松放
            (4, make_row(sprint="其他项目迭代")),               # 两边都跳过
        ]
        strict_ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        lenient_ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=False)

        strict_keys = {r["key"] for r in strict_ev["valid_rows"]}
        lenient_keys = {r["key"] for r in lenient_ev["valid_rows"]}
        assert strict_keys <= lenient_keys
        assert lenient_ev["importable"] == 2
        assert strict_ev["importable"] == 1

    def test_key_by_sheet_row_only_covers_valid_rows(self, session):
        """截图归属靠这张表 ⇒ 只有真正导入的行、其图片才入表。

        ⚠ 故事号 2026-09-18 起两路径都放过,这里把第 3 行的 key 改名,以便
          与原断言("第 3 行的故事号会拦住")下的场景区分得更清楚。
        """
        rows = [
            (2, make_row(自动编号="m0001")),
            (3, make_row(故事号="", 自动编号="m0003")),  # 故事号空,但现已不拦
            (4, make_row(sprint="", 自动编号="m0004")),
        ]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["key_by_sheet_row"] == {2: "m0001", 3: "m0003"}

    def test_covered_sprints_listed(self, session):
        rows = [(2, make_row()), (3, make_row(sprint="RobotClaw-Sprint 2", 故事号="4068"))]
        # RobotClaw-Sprint 2 → 8355/13899,换个项目才收 —— 这里只应有 13710 那条
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert [s["sprint_id"] for s in ev["sprints"]] == ["8354"]


class TestSprintScoping:
    """2026-09-19:导入范围由「整个项目」收窄到「所选迭代」。

    一份「问题明细表」本来就把多个迭代的行混在一起,按迭代分几次导入是现在的正常
    用法。故不属于所选迭代的行要**跳过并列原因**,而不是判错 —— 用户不需要为此改表,
    换个迭代再导一次即可。

    ⚠ 收窄比的是**归一化后解析出的 sprint_id**,不是表里的原文。这条如果退化成比原文,
      表里写 `BOTADP sprint 11`、库里是 `botadp-Sprint-11` 就会整批被判成"不属于本迭代",
      而用户看着迭代明明选对了却一行都导不进去 —— 静默、且指向错误的修法。
    """

    def test_rows_outside_selected_sprint_are_skipped(self, session):
        rows = [
            (2, make_row(自动编号="m0001")),                             # 8354 = 本次所选
            (3, make_row(sprint="botadp-Sprint-12", 自动编号="m0002")),  # 8356 同项目别的迭代
            (4, make_row(sprint="botadp-sprint12", 自动编号="m0003")),   # 同一个 8356,写法不同
        ]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True, sprint_id="8354")
        assert [r["key"] for r in ev["valid_rows"]] == ["m0001"]
        assert ev["skipped"]["other_sprint"] == 2
        assert ev["importable"] == 1

    def test_sprint_name_variants_still_match(self, session):
        """大小写/空格/连字符的差异不影响命中(比的是解析出的 sprint_id)。"""
        rows = [(2, make_row(sprint="BOTADP sprint 11"))]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True, sprint_id="8354")
        assert ev["importable"] == 1
        assert ev["skipped"]["other_sprint"] == 0

    def test_other_sprint_does_not_pollute_neighbour_buckets(self, session):
        """新分桶不能吞掉邻桶。

        原先的分桶靠 `reason.startswith(...)` 反推,加一个原因就得回去改那段推导,
        文案稍不留意新原因就会被算进邻桶 —— 界面上只会看到"属于其它项目"多了一批
        不该出现的行,没有任何报错。现在按 kind 计数,这条钉子守的就是它。
        """
        rows = [
            (2, make_row(sprint="botadp-Sprint-12", 自动编号="m0001")),  # 同项目别的迭代
            (3, make_row(sprint="其他项目迭代", 自动编号="m0002")),       # 别的项目
            (4, make_row(sprint="压根不存在", 自动编号="m0003")),         # 匹配不到同名迭代
            (5, make_row(sprint="", 自动编号="m0004")),                   # 未标注
        ]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True, sprint_id="8354")
        assert ev["skipped"]["other_sprint"] == 1
        assert ev["skipped"]["other_project"] == 1
        assert ev["skipped"]["unknown_sprint"] == 1
        assert ev["skipped"]["no_sprint"] == 1

    def test_project_check_runs_before_sprint_check(self, session):
        """判定顺序:别的项目的行要报成"不属于本项目",不能报成"不属于本迭代"。

        后者会把人引去反复确认迭代选对没有 —— 而真正该做的是换个项目再导一次。
        """
        rows = [(2, make_row(sprint="RobotClaw-Sprint 2"))]   # 8355 属 13899
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True, sprint_id="8354")
        assert ev["skipped"]["other_project"] == 1
        assert ev["skipped"]["other_sprint"] == 0

    def test_omitting_sprint_id_keeps_project_wide_scope(self, session):
        """不传 sprint_id = 纯项目口径(向后兼容)。

        两个 HTTP 端点都**强制要求**传(见 upload_doc_bugs),这个默认值只服务于
        直接调用本函数的脚本与测试;界面不存在"不选迭代"的路径。
        """
        rows = [(2, make_row()), (3, make_row(sprint="botadp-Sprint-12", 自动编号="m0002"))]
        ev = evaluate_doc_bug_rows(session, HEADERS, rows, "13710", strict=True)
        assert ev["importable"] == 2
        assert ev["skipped"]["other_sprint"] == 0


class TestNormalizeSprintName:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("RobotClaw-Sprint 2", "RobotClaw-Sprint2"),
            ("botadp-Sprint-11", "BOTADP sprint 11"),
            ("A_B-C", "ab c"),
        ],
    )
    def test_equivalent_names_collapse(self, a, b):
        assert normalize_sprint_name(a) == normalize_sprint_name(b)

    def test_distinct_names_stay_distinct(self):
        assert normalize_sprint_name("Sprint-1") != normalize_sprint_name("Sprint-11")


class TestValidateRouteShape:
    """校验接口返回的**结构**必须能被前端三态渲染直接吃下。"""

    def test_response_keys_present(self, session, monkeypatch):
        """不打 HTTP,直接核对 evaluate 的回吐 + 路由里拼的字段是否齐全。"""
        ev = evaluate_doc_bug_rows(session, HEADERS, [(2, make_row())], "13710", strict=True)
        # 路由里的三态判据:header_ok / valid / importable
        assert ev["ok"] is True and ev["importable"] == 1
        for key in ("total_count", "importable", "errors", "invalid_detail",
                    "skipped", "sprints", "key_by_sheet_row"):
            assert key in ev, f"evaluate 少了 {key}"

    def test_scan_is_readonly(self, session):
        """只读性:整个校验过程不允许出现任何写操作。"""
        calls: list[str] = []
        real = session.execute

        def spy(stmt, params=None):
            calls.append(str(stmt))
            return real(stmt, params)

        session.execute = spy  # type: ignore[method-assign]
        evaluate_doc_bug_rows(session, HEADERS, [(2, make_row())], "13710", strict=True)
        for sql in calls:
            upper = sql.upper()
            for verb in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
                assert verb not in upper, f"校验路径出现了写操作:{sql[:100]}"
