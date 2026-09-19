"""Sprint 展示屏蔽名单管理接口

对应表 rdm_sprint_exclude —— 人工维护的「不参与前端展示」Sprint 名单。
名单内的 Sprint 会从四处展示入口一并消失:

    A 报表页 Sprint 时间轴      GET /api/reports/db-sprints/{id}
    B 报表页 趋势图/重开数分布  GET /api/reports/project-metrics/{id}
    C 数据导入 Sprint 下拉      GET /api/data-import/sprints/{id}
    D 作业页 手动执行 Sprint 下拉 GET /api/reports/sprints/{id}

屏蔽只在读取侧生效,rdm_sprint 中的原始行不受影响,故解屏蔽是即时的。
判定与降级策略详见 api/services/sprint_filter.py。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user_from_header
from api.services import sprint_filter as svc

router = APIRouter(prefix="/api/sprint-filter", tags=["Sprint展示屏蔽"])


class ExcludeRequest(BaseModel):
    """加入屏蔽名单的请求体"""

    sprint_id: str = Field(..., description="要屏蔽的 Sprint id(对应 rdm_sprint.sprint_id)")
    reason: str | None = Field(None, description="屏蔽原因(便于日后回溯为什么屏蔽)")


@router.get("")
async def list_excluded(current_user: dict = Depends(get_current_user_from_header)):
    """查看当前屏蔽名单(按加入时间倒序)"""
    return svc.list_excluded()


@router.post("")
async def add_excluded(
    payload: ExcludeRequest,
    current_user: dict = Depends(get_current_user_from_header),
):
    """把一个 Sprint 加入屏蔽名单;已存在则覆盖原因(幂等)。

    不校验该 Sprint 是否已存在于 rdm_sprint —— 作业页下拉取自 RDM 实时数据,
    本地表可能尚未同步,此时仍应允许先屏蔽。
    """
    try:
        return svc.add_excluded(payload.sprint_id, reason=payload.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{sprint_id}")
async def remove_excluded(
    sprint_id: str,
    current_user: dict = Depends(get_current_user_from_header),
):
    """把一个 Sprint 移出屏蔽名单,解屏蔽即时生效"""
    if not svc.remove_excluded(sprint_id):
        raise HTTPException(status_code=404, detail=f"Sprint {sprint_id} 不在屏蔽名单中")
    return {"sprint_id": sprint_id, "removed": True}
