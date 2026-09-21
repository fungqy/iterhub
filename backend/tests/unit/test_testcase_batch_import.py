"""批量用例导入(2026-09-21,一次上传多份 CSV)的护栏。

与 test_doc_import_guards.py 的分工:那个文件守的是**文档故障导入**那一路的外圈约定
(上传白名单、sheet 名、openpyxl 补丁、同步 def);这里守的是用例导入改批量之后新出现的
几条约定 —— 它们都属于「改回去也不会报错、只会安静地坏」的那类:

  1. 请求级与文件级失败的分界:后缀不对 ⇒ 整批 400;内容问题 ⇒ 只拒那一份;
  2. 批量汇总的口径:**至少一份 valid** 才算 success(不是全部 valid);
  3. 逐份报告与文件级失败报告必须**同形** —— 前端共用一套块渲染;
  4. 路由继续是同步 def(解析重活不能占事件循环);
  5. 端点的入参名是 `files`(复数)且不含 `file`(单数)。
"""

from __future__ import annotations

import inspect
import io

import pytest
from fastapi import HTTPException, UploadFile

from api.routes import data_import as di


def _upload(filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(b""), filename=filename)


def _evaluated(**overrides):
    """evaluate_testcase_import 的最小产物 —— 只为让 testcase_report 能跑起来。"""
    base = {
        "project_id": "P1",
        "ok": True,
        "fatal": False,
        "total_rows": 3,
        "case_count": 1,
        "step_count": 2,
        "skipped": {},
        "case_sets": [],
        "rows": [{"case_id": "C-1"}],
        "case_refs": {"C-1": ["S-1"]},
        "stories": [],
        "missing_stories": [],
        "errors": [],
    }
    base.update(overrides)
    return base


# ══ 1. 请求级 vs 文件级 ═════════════════════════════════════════
class TestRequireTestcaseFiles:
    def test_accepts_all_csv(self):
        """大小写不敏感,与 _require_csv 同源。"""
        di.require_testcase_files([_upload("a.csv"), _upload("B.CSV")])

    def test_one_bad_extension_rejects_the_whole_batch(self):
        """⚠ 后缀是**请求级**约定:混进 .xlsx 必须整批 400,而不是把它降级成一份报告。

        那是调用方写错(前端已按 accept/正则拦过),安静地「导了其余几份」只会让这个
        错误再也没人发现;反过来,把内容问题(故事号查不到)升级成 400 又会一份坏文件
        毁掉整批 —— 两侧的分界必须钉死。
        """
        with pytest.raises(HTTPException) as ei:
            di.require_testcase_files([_upload("a.csv"), _upload("b.xlsx")])
        assert ei.value.status_code == 400
        assert ".csv" in ei.value.detail


# ══ 2. 汇总口径 ════════════════════════════════════════════════
class TestBatchReport:
    def test_success_is_any_valid_not_all(self):
        """⚠ 一份被拒不该拖住整批 —— 这正是「批量」的意义。"""
        batch = di.testcase_batch_report([
            di.testcase_file_error("a.csv", "boom", project_id="P1"),
            {"valid": True, "imported": 4},
        ])
        assert batch["success"] is True
        assert batch["file_count"] == 2
        assert batch["valid_count"] == 1

    def test_all_rejected_is_not_success(self):
        batch = di.testcase_batch_report([
            di.testcase_file_error("a.csv", "boom", project_id="P1"),
            di.testcase_file_error("b.csv", "boom", project_id="P1"),
        ])
        assert batch["success"] is False
        assert batch["valid_count"] == 0

    def test_imported_sums_across_files(self):
        """被拒的文件没有 imported ⇒ 按 0 计,不能把 None 带进加法。"""
        batch = di.testcase_batch_report([
            {"valid": True, "imported": 4},
            {"valid": True, "imported": 6},
            {"valid": False},
        ])
        assert batch["imported"] == 10


# ══ 3. 两份报告同形 ════════════════════════════════════════════
class TestReportShapeParity:
    def test_file_error_has_same_keys_as_normal_report(self):
        """⚠ 前端同一套块渲染整批文件:少一个 key 就是界面上一个 undefined。"""
        normal = di.testcase_report(
            _evaluated(), filename="a.csv", encoding="utf-8", file_size=12
        )
        failed = di.testcase_file_error("b.csv", "boom", project_id="P1")
        assert set(failed) == set(normal)


# ══ 4 / 5. 路由约定 ════════════════════════════════════════════
class TestRoutesStaySync:
    @pytest.mark.parametrize("handler", [di.upload_testcases, di.validate_testcases])
    def test_not_coroutine_function(self, handler):
        assert not inspect.iscoroutinefunction(handler), (
            f"{handler.__name__} 又被写回 async def 了:同步重活会独占事件循环"
        )

    @pytest.mark.parametrize("handler", [di.upload_testcases, di.validate_testcases])
    def test_takes_files_plural(self, handler):
        """⚠ 退回单数 `file` 会让「一次上传多份」在**接口层**就失效。"""
        sig = inspect.signature(handler)
        assert "files" in sig.parameters
        assert "file" not in sig.parameters
