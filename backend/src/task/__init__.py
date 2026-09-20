"""后台任务包(只做导出声明)。

⚠ 历史问题(2026-09-20 修正):
1. 写的是 `all = [...]` 而非 `__all__`,等于既没导出也没约束,`from task import *` 不生效;
2. 别名 `process_rdm_data` 全仓无任何引用,属于会误导人的死接口。
调用方一律直接 `from task.report_rdm_data import process_sprint`。
"""

from .report_rdm_data import process_sprint

__all__ = ["process_sprint"]
