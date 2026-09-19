import csv
import io
import json
import logging
import os
import re
import tempfile
import time
from datetime import date, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from openpyxl import load_workbook
from openpyxl.styles.fills import Fill
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel
from sqlalchemy import bindparam, text

from api.auth import get_current_user_flexible, get_current_user_from_header
from api.services.doc_bug_images import has_drawing, iter_doc_bug_image_rows
from api.services.execution_log import now_beijing
from api.services.sprint_filter import exclude_sql
from db.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-import", tags=["数据导入"])

# 单个上传文件最大字节数(默认 400MB)。可通过环境变量 MAX_UPLOAD_BYTES 覆盖。
# ⚠ 「应用平台现场问题沟通新.xlsx」内嵌 390 张现场截图，单文件实测 297MB，旧的
#   20MB 上限会把这份唯一的真实数据源直接 413 拒掉。解析走 openpyxl 的 read_only
#   模式(xl/media 根本不读)，内存占用与截图体积无关,故上限只需覆盖上传带宽。
# ⚠ 反向代理侧还有一道 client_max_body_size 要同步放开，否则请求到不了这里:
#   frontend/nginx.conf(compose)与 deployment.yml 的 ConfigMap。前者原先根本没写,
#   吃的是 nginx 默认 1MB —— 也就是说改这个常量之前,连 5MB 的 Excel 都传不上来。
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(400 * 1024 * 1024)))

# 落盘分块大小:整文件 read() 进内存会让峰值随截图数量线性涨(297MB 文件峰值翻倍)
_UPLOAD_CHUNK = 1024 * 1024

# ── openpyxl 的 Fill 容错补丁(进程级,**一次性,永不还原**)────────────────
# 病根:源表里有 `<fill>` 缺 patternType/fgColor,openpyxl 的 Fill.__init__ 会直接
#   抛 TypeError,导致整份文件读不下去。
#
# ⚠ 为什么不在 load_workbook() 前后 patch/unpatch(2026-09-17 改):
#   那是在改**进程级**类属性,并发导入下必然竞态 —— 先结束的那个请求把补丁撤掉,
#   另一个还在解析途中,于是又回到 TypeError,表现为随机的 500,且日志里看不到原因。
#   而 upload_doc_bugs / validate_doc_bugs 现在跑在线程池里(见那两个路由的注释),
#   并发是常态,不是边角情形。
# ⚠ 常驻是否有副作用:补丁只在「原始构造抛 TypeError」时回落成空值,是对原行为的**超集**,
#   正常文件的解析结果完全不变;本进程内另一处 openpyxl 消费方(task/report_wiki_data.py
#   读 wiki 附件)也一并受益 —— 它同样可能碰到残缺 fill。
def _tolerant_fill_init(self, *args, **kwargs):
    try:
        _original_fill_init(self, *args, **kwargs)
    except TypeError:
        self.patternType = None
        self.fgColor = None
        self.bgColor = None


_original_fill_init = Fill.__init__
Fill.__init__ = _tolerant_fill_init


def _reject_oversize_upload(request: Request) -> None:
    """在读 body 之前先看 Content-Length,直接拒掉过大的上传,
    避免恶意请求把整文件读进内存再 OOM。"""
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大(Content-Length={cl} > {MAX_UPLOAD_BYTES} 字节)",
                )
        except ValueError:
            pass  # 非法 header 不阻断,交给 read 阶段再判断


def _require_xlsx(file: UploadFile) -> None:
    """只接受 .xlsx(2026-09-17 收口)。

    ⚠ 此前前后端都宣称支持「.xlsx / .xls」,而后端解析用的是 openpyxl ——
      它**读不了** OLE2 的老版 .xls,会抛 InvalidFileException,被兜底 except 转成
      500「处理文件失败」。也就是说:一个被界面允许的格式,必然得到一条看不懂的报错。
    ⚠ 大小写不敏感:`.XLSX` 是合法的 Excel 后缀(浏览器 accept 本来也忽略大小写),
      原先的 endswith((".xlsx", ".xls")) 会把 `A.XLSX` 拒掉。
    ⚠ 与前端 DocBugImport.vue 的 chooseLabel/accept/正则同口径,改一处要同步另一处。
    """
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="仅支持 .xlsx 格式（Excel 2007+）；老版 .xls 请先另存为 .xlsx",
        )


@router.get("/sprints/{project_id}")
async def list_closed_sprints(
    project_id: int,
    current_user: dict = Depends(get_current_user_from_header)
):
    with get_session() as session:
        query = text("SELECT project_id FROM project_configs WHERE id = :project_id")
        result = session.execute(query, {"project_id": project_id})
        row = result.fetchone()

        if not row:
            return []

        jira_project_id = row[0]

        # 排除已被屏蔽展示的 Sprint(rdm_sprint_exclude);表不可用时 exclude_sql 返回空串
        sprints_query = text(f"""
            SELECT s.sprint_id, s.sprint_name
            FROM rdm_sprint s
            WHERE s.project_id = :jira_project_id
            AND s.state = 'closed'
            {exclude_sql('s')}
            GROUP BY s.sprint_id, s.sprint_name
            ORDER BY s.sprint_id DESC
        """)
        sprints_result = session.execute(sprints_query, {"jira_project_id": jira_project_id})

        sprints = []
        for sprint_row in sprints_result:
            sprints.append({
                "sprint_id": sprint_row[0],
                "sprint_name": sprint_row[1],
            })
        return sprints


# ============================================================
# 文档故障导入
# ============================================================
# 数据源:docs/应用平台现场问题沟通新.xlsx 的「问题明细表」(单 sheet、26 列 A..Z)。
# 与旧版(按「问题编号/提出时间/完成时间/问题类型」找列)的差异见 docs/plans 的改版方案。
#
# 两条**决定成败**的口径:
#   1. 迭代归属由表内【sprint】列决定,不由上传参数决定。
#      只有填了 sprint 且能匹配到迭代的行才会入库;空 sprint 的行直接跳过
#      (该表现有 480 行里只有 43 行标了 sprint,其余 437 行属"尚未归属")。
#   2. 【sprint】是**人写的迭代名**,和 rdm_sprint.sprint_name 不一定逐字相同:
#      实测表里写 `RobotClaw-Sprint 2`,库里是 `RobotClaw-Sprint2`(多一个空格)。
#      故走「去空白/连字符 + 忽略大小写」归一化匹配,否则会静默漏掉整批行。

DOC_BUG_SHEET_NAME = "问题明细表"

# 字段 → 候选表头(按顺序取第一个命中的)。旧表头名保留为别名,便于同一套逻辑吃旧文件。
COLUMN_ALIASES: dict[str, list[str]] = {
    "key": ["自动编号", "问题编号"],
    "priority": ["优先级"],
    "maker": ["处理人"],
    "status": ["处理状态"],
    "resolve_method": ["处理方式"],
    "func": ["功能点"],
    "desc": ["问题详述"],
    "propose_time": ["创建日期", "提出时间"],
    "verify_note": ["验证备注"],
    "sprint_name": ["sprint", "Sprint", "迭代"],
    "story_key": ["故事号"],
    "category": ["问题类别", "问题类型"],
    "reason": ["原因分析"],
    "opinion": ["处理意见"],
    "resolve_time": ["解决日期", "完成时间"],
    "is_repeated": ["反复"],
    "is_occasional": ["偶发"],
    "last_editor": ["最后编辑人"],
    "last_edit_time": ["最后编辑时间"],
    "bounce_count": ["打回次数"],
    "rdm_key": ["rdm"],
}

# ── 两级校验(勿混)────────────────────────────────────────────
# 「列级」:表头里有没有这一列。缺一即整次导入失败。
REQUIRED_COLUMNS = {"key": "自动编号", "desc": "问题详述", "sprint_name": "sprint"}

# 「行级必填」:这一列存在,但**该行的值不能为空**。为空则拦下这一行(不是整批)。
# ⚠ 与 REQUIRED_COLUMNS 是两回事:REQUIRED_COLUMNS 管"列在不在",本表管"值填没填"。
# ⚠ 清单来自用户拍板(2026-09-17 / 2026-09-18),增删都属**可见的口径变更**:
#   故事号原列入此表(2026-09-17),源表 481 行里真正能通过的只剩 2 行;后用户改口
#   (2026-09-18),故事号不再作为行级必填 —— 校验时不再拦下故事号为空或不合法
#   的行,故事号仍保留在结果行里供 DOC 详情弹窗展示。
# ⚠ 「问题详述」不在此表:它已在 REQUIRED_COLUMNS 的表头级校验里,行级由
#   build_doc_bug_row 的既有分支继续兜(两处都写着会重复报错,故只留后者)。
REQUIRED_ROW_FIELDS: dict[str, str] = {
    "key": "自动编号",
    "sprint_name": "sprint",
    "priority": "优先级",
    "maker": "处理人",
    "status": "处理状态",
    "category": "问题类别",
}

# 优先级原值直通。注意「优化」是新表原生值 —— 旧口径里它是「低」的转换结果,
# 现在两者并存且落进同一个展示桶,不冲突。
VALID_PRIORITIES = {"极高", "高", "中", "低", "优化"}

VALID_STATUSES = {
    "不处理", "处理中", "待测试", "继续观察", "未开始",
    "验证通过", "已解决", "转任务", "转需求",
    "已排期",  # 新表新增(58 行)
}

# 【问题类别】→ rdm_doc_bug.type（落库值）。
#
# ⚠ 09-17 拍板：**规范词表以源表用词为准**（reports.py 的 CANONICAL_TAGS =
#   代码问题/需求完善/功能优化/环境问题/沟通问题/模型能力问题/其他）。
#   原先这里有 `代码问题 → 代码实现`，与拍板**方向相反**，导致源表写「代码问题」
#   入库却成「代码实现」、图上分裂成两个扇区。已把目标词改回「代码问题」。
#
# 本表仍然保留：它是**落库前的归一化**（把历史/别名的写法收敛到规范词），
# 不是「源表用词 → 旧报表用词」。右侧值必须恒为 CANONICAL_TAGS 的成员。
# ⚠ 后半段几个键（代码逻辑问题/漏做/第三方影响/需求问题）来自**另一个数据源的
#   标签词表**（数据工具链平台，见 sql/iterdb-0915.sql 的 DDL 注释），
#   当前这份 Excel 用不到，但作为**防御性别名**保留 —— 删掉会让那种输入整批落「其他」。
# 未识别的类别归「其他」而不是拒行:类别是人工维护的开放语义,新值出现时不该整批导入失败。
CATEGORY_MAP: dict[str, str] = {
    # —— 源表现用词（同词映射，写明以便「规范词表全覆盖」一眼可查）——
    "代码问题": "代码问题",
    "需求完善": "需求完善",
    "功能优化": "功能优化",
    "环境问题": "环境问题",
    "沟通问题": "沟通问题",
    "模型能力问题": "模型能力问题",
    # —— 历史/他源别名 ——
    "代码逻辑问题": "代码问题",
    "漏做": "代码问题",
    "需求问题": "需求完善",
    "第三方影响": "环境问题",
}

# 返回给前端的错误明细上限,避免一份烂文件回吐几百条
MAX_REPORTED_ERRORS = 50


class DocBugItem(BaseModel):
    key: str | None = None
    name: str | None = None
    priority: str | None = None
    reason: str | None = None
    resolve_method: str | None = None
    maker: str | None = None
    propose_time: datetime | None = None
    resolve_time: datetime | None = None
    status: str | None = None
    type: str | None = None
    original_type: str | None = None
    sprint_id: str | None = None
    project_id: str | None = None
    story_key: str | None = None
    verify_note: str | None = None
    is_repeated: str | None = None
    is_occasional: str | None = None
    last_editor: str | None = None
    last_edit_time: datetime | None = None
    bounce_count: int | None = None
    rdm_key: str | None = None


DOC_BUG_SELECT_COLUMNS = """
    d.`key`, d.`name`, d.priority, d.reason, d.resolve_method, d.maker,
    d.propose_time, d.resolve_time, d.status, d.`type`, d.original_type,
    d.sprint_id, s.sprint_name, d.project_id,
    d.story_key, d.verify_note, d.is_repeated, d.is_occasional,
    d.last_editor, d.last_edit_time, d.bounce_count, d.rdm_key
"""


def _doc_bug_row_to_item(row) -> dict[str, Any]:
    """DOC_BUG_SELECT_COLUMNS 的一行 → 接口字典。

    列表与单条详情共用同一份映射,免得加字段时只改一处、另一处静默缺列。
    """
    return {
        "key": row[0],
        "name": row[1],
        "priority": row[2],
        "reason": row[3],
        "resolve_method": row[4],
        "maker": row[5],
        "propose_time": row[6].isoformat() if row[6] else None,
        "resolve_time": row[7].isoformat() if row[7] else None,
        "status": row[8],
        "type": row[9],
        "original_type": row[10],
        "sprint_id": str(row[11]) if row[11] else None,
        "sprint_name": row[12],
        "project_id": str(row[13]) if row[13] else None,
        "story_key": row[14],
        "verify_note": row[15],
        "is_repeated": row[16],
        "is_occasional": row[17],
        "last_editor": row[18],
        "last_edit_time": row[19].isoformat() if row[19] else None,
        "bounce_count": row[20],
        "rdm_key": row[21],
    }


@router.get("/doc-bugs")
async def list_doc_bugs(
    project_id: str = Query(..., description="JIRA项目ID"),
    sprint_id: str | None = Query(None, description="Sprint ID(可选,不传则返回该项目全部)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user_from_header)
):
    """按项目维度列出已导入的文档故障(可选再按 Sprint 过滤)。

    展示范围改成项目而不是重点项目内某一个 Sprint:导入本身已由表内 sprint 列
    决定归属,一个项目下会同时存在多个 Sprint 的文档故障。
    """
    where = "d.project_id = :project_id"
    params: dict[str, Any] = {"project_id": project_id}
    if sprint_id:
        where += " AND d.sprint_id = :sprint_id"
        params["sprint_id"] = sprint_id

    with get_session() as session:
        total = session.execute(
            text(f"SELECT COUNT(*) FROM rdm_doc_bug d WHERE {where}"), params
        ).fetchone()[0]   # type: ignore[attr-defined]

        data_result = session.execute(text(f"""
            SELECT {DOC_BUG_SELECT_COLUMNS}
            FROM rdm_doc_bug d
            LEFT JOIN rdm_sprint s ON s.sprint_id = d.sprint_id
            WHERE {where}
            ORDER BY d.sprint_id DESC, d.`key`
            LIMIT :limit OFFSET :offset
        """), {**params, "limit": page_size, "offset": (page - 1) * page_size})

        items = [_doc_bug_row_to_item(row) for row in data_result]

        return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/doc-bug")
async def get_doc_bug(
    key: str = Query(..., description="文档故障编码"),
    current_user: dict = Depends(get_current_user_from_header),
):
    """单条文档故障的完整字段 —— 供故障明细里的「文档故障详情」弹窗使用。

    列表接口只回吐列表需要的列(编号/名称/开发/级别/来源),详情需要全字段(原因分析、
    处理方式、验证备注、故事号、反复/偶发…),故单取一条。响应很小(单行文本,不含
    截图二进制),截图另有 /doc-bug-images(清单)与 /doc-bug-image/{id}(二进制)。
    """
    with get_session() as session:
        row = session.execute(text(f"""
            SELECT {DOC_BUG_SELECT_COLUMNS}
            FROM rdm_doc_bug d
            LEFT JOIN rdm_sprint s ON s.sprint_id = d.sprint_id
            WHERE d.`key` = :key
        """), {"key": key}).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="文档故障不存在")
    return _doc_bug_row_to_item(row)


class ClearDocBugsRequest(BaseModel):
    project_id: str
    sprint_id: str | None = None


@router.delete("/doc-bugs")
async def clear_doc_bugs(
    request: ClearDocBugsRequest,
    current_user: dict = Depends(get_current_user_from_header)
):
    """清空某项目(或该项目下某 Sprint)的文档故障。sprint_id 不传 = 清空整个项目。"""
    where = "project_id = :project_id"
    params: dict[str, Any] = {"project_id": request.project_id}
    if request.sprint_id:
        where += " AND sprint_id = :sprint_id"
        params["sprint_id"] = request.sprint_id

    with get_session() as session:
        try:
            result = session.execute(text(f"DELETE FROM rdm_doc_bug WHERE {where}"), params)
            session.commit()
            return {"deleted": result.rowcount}   # type: ignore[attr-defined]
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=500, detail=f"清除数据失败: {e!s}")


@router.get("/doc-bug-images")
async def list_doc_bug_images(
    key: str = Query(..., description="文档故障编码"),
    current_user: dict = Depends(get_current_user_from_header),
):
    """某条文档故障的截图清单 —— 只有元数据,不含二进制,故响应极小。

    与出图接口分开,是为了让「打开详情」的两步各自可缓存、可失败:元数据失败只影响
    缩略图带,图片失败只影响那一个格子。混成一个接口会把大二进制拖进首屏关键路径。
    """
    with get_session() as session:
        rows = session.execute(text("""
            SELECT id, seq, column_label, mime_type, byte_size, width, height,
                   thumb_mime, thumb_byte_size
            FROM rdm_doc_bug_image
            WHERE doc_bug_key = :key
            ORDER BY seq
        """), {"key": key}).fetchall()

    items = [
        {
            "id": r[0],
            "seq": r[1],
            "column_label": r[2],
            "mime_type": r[3],
            "byte_size": r[4],
            "width": r[5],
            "height": r[6],
            "thumb_mime": r[7],
            "thumb_byte_size": r[8],
        }
        for r in rows
    ]
    return {"key": key, "total": len(items), "items": items}


@router.get("/doc-bug-image/{image_id}")
async def get_doc_bug_image(
    image_id: int,
    thumb: int = Query(0, ge=0, le=1, description="1=缩略图, 0=原图"),
    if_none_match: str = Header(None),
    current_user: dict = Depends(get_current_user_flexible),
):
    """从 BLOB 读出图片字节。ETag = 内容 sha256 ⇒ 命中 If-None-Match 直接 304。

    为什么是「后端出图 + query token」而不是 nginx 静态目录:
      · 静态目录要么免鉴权(内网谁都能拉),要么再配一套 auth_request,复杂度反而更高;
      · 且 nginx 配置在本项目有**两份**(frontend/nginx.conf 与 deployment.yml 的
        ConfigMap),加一次静态路由就要同步两处 —— client_max_body_size 已经踩过这个坑。
    后端出图的代价是占用应用进程的带宽与内存,但 **ETag/304 让二次打开几乎零成本**,
    正好对冲「打开详情不能慢」这条硬约束。缩略图与原图用不同 ETag(后缀 -t),互不串。

    ⚠ 本接口的鉴权走 get_current_user_flexible(允许 ?t=<token>),因为 <img> 带不了
      请求头;token 因此可能出现在 URL 里,故**只读、不可用于任何写操作**。
    """
    with get_session() as session:
        row = session.execute(text("""
            SELECT mime_type, thumb_mime, sha256, `data`, thumb
            FROM rdm_doc_bug_image
            WHERE id = :id
        """), {"id": image_id}).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="截图不存在")

    mime_type, thumb_mime, sha256, data, thumb_blob = row
    if thumb:
        if not thumb_blob:
            raise HTTPException(status_code=404, detail="该截图没有缩略图")
        payload, content_type = bytes(thumb_blob), (thumb_mime or "image/webp")
        etag = f'"{sha256}-t"' if sha256 else None
    else:
        payload, content_type = bytes(data), (mime_type or "image/png")
        etag = f'"{sha256}"' if sha256 else None

    headers = {"Cache-Control": "private, max-age=604800"}
    if etag:
        headers["ETag"] = etag
        if if_none_match:
            # 客户端可能回传 W/"..." 或一串 tag,逐个归一后比对
            sent = {v.strip().removeprefix("W/").strip() for v in if_none_match.split(",")}
            if etag in sent:
                return Response(status_code=304, headers=headers)

    return Response(content=payload, media_type=content_type, headers=headers)


def parse_maker(raw: str) -> str:
    """【处理人】→ 产生人。@ / 换行 / 中文逗号都归一成英文逗号后取最后一个非空段。

    表里 79 行是「郭秦逸, 李若谷」这类多值,约定取末位 = 实际承担人。
    """
    if not raw:
        return ""
    cleaned = raw.replace("@", ",").replace("\n", ",").replace("，", ",").replace("\r", ",")
    parts = [p.strip() for p in cleaned.split(",")]
    parts = [p for p in parts if p]
    return parts[-1] if parts else ""


DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y年%m月%d日",   # 【最后编辑时间】的真实格式,如「2026年9月7日」
    "%Y-%m-%dT%H:%M:%S",
)


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        for fmt in DATETIME_FORMATS:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def normalize_sprint_name(name: str | None) -> str:
    """迭代名归一化:去掉空白与连字符并忽略大小写。

    实测差异:`RobotClaw-Sprint 2`(表) vs `RobotClaw-Sprint2`(库)。
    全库 67 个 sprint 归一化后零冲突,故可以放心做 key 匹配。
    """
    return re.sub(r"[\s\-_]+", "", name or "").lower()


# 故事号形如 `EMBODIED_ADP-4068`,尾部数字段就是源表【故事号】列填的东西。
_STORY_SUFFIX_RE = re.compile(r"^(\d+)$")


def looks_like_story_suffix(raw: str) -> bool:
    """源表【故事号】列的取值形态:纯数字(如 `4068`)。"""
    return bool(_STORY_SUFFIX_RE.match((raw or "").strip()))


def _load_story_index(session) -> dict[str, list[tuple[str, str]]]:
    """``issue_key`` 尾部数字段 → [(issue_key, sprint_id), …] 的倒排索引。

    为什么要建倒排而不是逐行 LIKE:一份表几百行、每行一次查询就是几百次往返,
    而 rdm_issue 全表才两千多行 —— 一次全量拉回来在内存里查更省。

    ⚠⚠ **后缀不唯一是这个索引存在的理由**:实测全库有 15 个后缀各自横跨 5 个不同的
    sprint(如 `-113` 在 EMBODIED_ADP/CMP/JSST/ROBOTCLAW/MOWING 下各有一条)。
    ⇒ 只凭"后缀能在 rdm_issue 里找到"就放过,会把别的项目的故事判成合法。
    故命中多条时**必须再按本行的 sprint 消歧**(见 resolve_story_key)。
    """
    rows = session.execute(text("""
        SELECT issue_key, sprint_id FROM rdm_issue
        WHERE issue_key IS NOT NULL AND issue_key <> ''
    """)).fetchall()

    index: dict[str, list[tuple[str, str]]] = {}
    for issue_key, sprint_id in rows:
        suffix = str(issue_key).rsplit("-", 1)[-1]
        index.setdefault(suffix, []).append((str(issue_key), str(sprint_id or "")))
    return index


def resolve_story_key(
    raw: str,
    sprint_id: str | None,
    story_index: dict[str, list[tuple[str, str]]],
) -> tuple[str | None, str | None]:
    """源表【故事号】的值 → 完整 issue_key;不合法时返回 (None, 原因)。

    三步,任一步不过都带着**可执行的原因**返回(调用方要原样呈现给用户):

    1. **形态**:必须是纯数字。库里 story_key 存的就是这个形态(见 DDL 注释
       「4068 → EMBODIED_ADP-4068」),填了完整 key 或横生枝节的值一律判错 ——
       与其猜"用户是不是想填完整 key",不如让 TA 直接看到期望的形态。
    2. **存在**:尾部数字段要能在 rdm_issue 的 issue_key 里命中。
    3. **对应**:命中的 issue 里,必须有**属于本行 sprint** 的那一个。

    ⚠ 第 3 步是「对应」的全部含义。同一个后缀可能横跨多个 sprint(见 _load_story_index),
    故这里按 sprint 求交:交集里恰好一个 ⇒ 通过;多个 ⇒ 后缀在本 sprint 内仍有歧义,
    报错并列出候选让人去 RDM 核;一个都没有 ⇒ 故事不属于这个迭代。
    """
    raw = (raw or "").strip()
    if not raw:
        return None, "[故事号]为空"

    if not looks_like_story_suffix(raw):
        return None, (
            f"[故事号] '{raw}' 应为故事编号(纯数字,如 4068),"
            f"库里会还原成 issue_key(如 EMBODIED_ADP-{raw})"
        )

    candidates = story_index.get(raw)
    if not candidates:
        return None, f"[故事号] '{raw}' 在 rdm_issue 中找不到对应的故事"

    if not sprint_id:
        # 没解析出 sprint 就没法判"对应",但这条不该走到这儿 —— 上一步已拦。
        return None, f"[故事号] '{raw}' 无法校验所属迭代"

    same_sprint = [k for k, sid in candidates if sid == str(sprint_id)]
    if len(same_sprint) == 1:
        return same_sprint[0], None
    if not same_sprint:
        return None, (
            f"[故事号] '{raw}' 解析为 {candidates[0][0]},"
            f"但它属于迭代 {candidates[0][1]},与本行 sprint 不一致"
        )
    return None, (
        f"[故事号] '{raw}' 在本迭代下匹配到多个故事: {'、'.join(same_sprint)},"
        f"请在 RDM 里确认后改填完整编号"
    )


def find_column_index(headers: list[str], candidates: list[str]) -> int | None:
    for candidate in candidates:
        for i, h in enumerate(headers):
            if h and h.strip() == candidate:
                return i
    return None


def cell_text(value: Any) -> str:
    """单元格 → 去空白字符串。日期型单元格先格式化再走同一套解析。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_doc_bug_sheet(
    path: str,
) -> tuple[list[str], list[tuple[int, list[str]]], int, str]:
    """读取工作簿 → (表头, [(行号, 各行文本)], 跳过的删除线行数, 实际读到的那张 sheet 名)。

    ⚠ 第四个返回值是给截图用的:下面 `DOC_BUG_SHEET_NAME in wb.sheetnames` 不成立时会兜底
      读 `wb.active`,而截图侧必须按 sheet 名精确定位 drawing。两边各自决定就会分叉 ——
      实测后果是「文本行照导、图片一张不入,且理由写着『源文件无内嵌图片』」。故这里把
      真正用的那张 sheet 名回传给调用方,由它原样交给 _sync_doc_bug_images。

    read_only + data_only:不加载 xl/media(390 张截图/296MB),也不求值公式。

    ⚠ 两条都是踩过的坑,改这段前先看这里:
    1. **必须 `ws.reset_dimensions()`。** 该工作簿的 `<dimension ref="A1">` 是错的
       (实际 26 列 × 481 行),而 read_only 的 iter_rows() 会拿 dimension 去夹
       (`max_row = max_row or self.max_row`) —— 不重置就只吐出 1 列 1 行,而且
       **不报错**。实测:重置前 1 行、重置后 481 行。
    2. **必须单遍遍历。** read_only 的行迭代器共用一个 xml 流,先 `next()` 取表头
       再另起一次 `iter_rows()` 会拿到 0 行(同样静默)。故这里只开一个迭代器,
       表头取第一行、数据行续着往下走。
    """
    wb = load_workbook(filename=path, read_only=True, data_only=True)

    try:
        sheet_name = DOC_BUG_SHEET_NAME if DOC_BUG_SHEET_NAME in wb.sheetnames else wb.active.title
        if sheet_name != DOC_BUG_SHEET_NAME:
            # 表名对不上是真出过的事(维护方改过 sheet 名),留一条日志便于对上"为什么截图少了"
            logger.warning(
                "工作簿里没有「%s」,已退用活动表「%s」(文本与截图都以它为准)",
                DOC_BUG_SHEET_NAME,
                sheet_name,
            )
        ws = wb[sheet_name]
        ws.reset_dimensions()

        row_iter = ws.iter_rows(min_row=1, min_col=1)
        header_cells = next(row_iter, None)
        if header_cells is None:
            return [], [], 0, sheet_name
        headers = [cell_text(c.value) for c in header_cells]

        rows: list[tuple[int, list[str]]] = []
        strikethrough_rows = 0
        for row_idx, row_cells in enumerate(row_iter, start=2):
            values = [cell_text(c.value) for c in row_cells]
            if not any(values):
                continue  # 尾部空行:不计入总数,也不算"跳过"
            # 删除线 = 维护方标掉的废弃行(该表当前没有,保留兼容)
            key_cell = row_cells[0] if row_cells else None
            font = getattr(key_cell, "font", None)
            if font is not None and getattr(font, "strikethrough", False):
                strikethrough_rows += 1
                continue
            rows.append((row_idx, values))
        return headers, rows, strikethrough_rows, sheet_name
    finally:
        wb.close()


def build_doc_bug_row(
    values: list[str],
    cols: dict[str, int | None],
    story_index: dict[str, list[tuple[str, str]]] | None = None,
    sprint_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """单行 → 入库字典;校验不过返回 (None, 原因)。

    ⚠ **本函数是行级校验的唯一口径** —— 导入与"导入前校验"两条路径都调它。
    若各自写一套,迟早出现"校验通过了却导不进来"(或反过来),而那种不一致
    用户只能靠肉眼比对两份报告发现,是最难查的一类 bug。

    两个可选参数决定校验强度,刻意做成"给了才有"而不是开关布尔量:

    * 都不给 ⇒ 沿用改版前的宽松判定(只查编号/详述/枚举值)。保留这条路径是为了
      在导入时**不引入新的拦截**:存量源表里 40 行故事号为空,若导入侧也按新口径拦,
      重导一份老表就会静默少 40 行 —— 用户看到的"导入成功 2 条"会与校验报告对不上。
      放宽导入、把口径问题交给校验步骤提前暴露,是这次拍板的取舍。
    * 给了 story_index/sprint_id ⇒ 启用**严格口径**:6 个必填列(自动编号 / sprint /
      优先级 / 处理人 / 处理状态 / 问题类别)的空值一律拦下。
      ⚠ 故事号曾在此口径下做"形态 → 存在 → 与本行 sprint 对应"三段校验,用户
        2026-09-18 拍板取消 —— 不再因为故事号为空 / 拼不上 issue_key 而拦行,
        故事号原值照旧进入结果行供 DOC 详情弹窗展示。
    """
    strict = story_index is not None

    def get_raw(field: str) -> str:
        """原值 —— 含两端空白,不做任何归一。"""
        idx = cols.get(field)
        if idx is None or idx >= len(values):
            return ""
        return values[idx]

    def get(field: str) -> str:
        """去空白后的值 —— 除「必填列空值判定」外一律用这个。

        ⚠⚠ 空值判定的口径**必须与写库口径一致**,否则同一份表在"校验"和"导入"
        两侧会给出不同行数,而这正是这次改动最想消灭的那类不一致。
        踩过的实例:源表那 27 行属于 RobotClaw 的行,【问题详述】原文是 `" "`(一个空格)。
        按原值判 `not " "` ⇒ False ⇒ **算填了**;可写库时 `cell_text()` 会 strip 掉,
        落的却是空串。用户看到"校验通过"却又看到库里是空的。
        ⇒ 一切"空不空"的判断都走这里(以及 build_doc_bug_row 里 parse_* 的返回值)。
        """
        return get_raw(field).strip()

    # ── 必填列空值(严格模式)─────────────────────────────────
    # 按 REQUIRED_ROW_FIELDS 的声明顺序检查,故报错顺序稳定、可预期。
    if strict:
        for field, label in REQUIRED_ROW_FIELDS.items():
            if not get(field):
                return None, f"[{label}]为空"

    key_val = get("key")
    if not key_val:
        return None, "[自动编号]为空"

    desc_val = get("desc")
    if not desc_val:
        return None, "[问题详述]为空"

    # 枚举值同样按去空白后的值比对:源表里 `" 高"` 这类值不该被判成非法枚举。
    priority_val = get("priority")
    if priority_val and priority_val not in VALID_PRIORITIES:
        return None, (
            f"[优先级] '{priority_val}' 不在有效范围内, 有效值: "
            f"{'、'.join(sorted(VALID_PRIORITIES))}"
        )

    status_val = get("status")
    if status_val and status_val not in VALID_STATUSES:
        return None, (
            f"[处理状态] '{status_val}' 不在有效范围内, 有效值: "
            f"{'、'.join(sorted(VALID_STATUSES))}"
        )

    # ── 故事号:不再做强校验(用户 2026-09-18)──
    # 此前在 strict 模式下还会"形态 → 存在 → 与本行 sprint 对应"三段判定,
    # 拦掉了 14 行故事号为空或拼不上 issue_key 的行;用户拍板改成只把原值透传,
    # 由 DOC 详情弹窗照旧展示源表里填的那个数。空值也照常入库(为 None),
    # 不再做"为空即拦"的拦截 —— 该拦截已从 REQUIRED_ROW_FIELDS 移除。
    story_key_val = get_raw("story_key")

    func_val = get("func")
    name_val = f"{func_val}>{desc_val}" if func_val else desc_val

    reason_val = get("reason")
    opinion_val = get("opinion")
    if reason_val:
        reason_final = f"{reason_val}>{opinion_val}" if opinion_val else reason_val
    else:
        reason_final = opinion_val

    category_raw = get("category")

    return {
        "key": key_val,
        "name": name_val,
        "priority": priority_val,
        "reason": reason_final,
        "resolve_method": get("resolve_method"),
        "maker": parse_maker(get("maker")),
        "propose_time": parse_datetime(get("propose_time")),
        "resolve_time": parse_datetime(get("resolve_time")),
        "status": status_val,
        # 空类别落「其他」而非空串 —— 与 reports.py 的 parse_tag 空值口径一致,
        # 也让「未填类别」在图上可见(落空串会被 parse_tag 兜成「其他」,但库值不自洽)。
        "type": CATEGORY_MAP.get(category_raw, "其他") if category_raw else "其他",
        "original_type": category_raw,
        "story_key": story_key_val,
        "verify_note": get("verify_note"),
        "is_repeated": get("is_repeated"),
        "is_occasional": get("is_occasional"),
        "last_editor": get("last_editor"),
        "last_edit_time": parse_datetime(get("last_edit_time")),
        "bounce_count": parse_int(get("bounce_count")),
        "rdm_key": get("rdm_key"),
        "sprint_id": None,
        "project_id": None,
    }, None


# 幂等写入:key 上建了唯一键(uk_doc_bug_key),同一份文件重导只会更新既有行。
# 用 8.0.19+ 的「行别名」写法而不是已废弃的 VALUES(col) —— 线上是 MySQL 8.4。
UPSERT_DOC_BUG_SQL = text("""
    INSERT INTO rdm_doc_bug
        (`key`, `name`, priority, reason, resolve_method, maker, propose_time, resolve_time,
         status, `type`, original_type, sprint_id, project_id,
         story_key, verify_note, is_repeated, is_occasional, last_editor, last_edit_time,
         bounce_count, rdm_key)
    VALUES
        (:key, :name, :priority, :reason, :resolve_method, :maker, :propose_time, :resolve_time,
         :status, :type, :original_type, :sprint_id, :project_id,
         :story_key, :verify_note, :is_repeated, :is_occasional, :last_editor, :last_edit_time,
         :bounce_count, :rdm_key)
    AS new
    ON DUPLICATE KEY UPDATE
        `name` = new.`name`, priority = new.priority, reason = new.reason,
        resolve_method = new.resolve_method, maker = new.maker,
        propose_time = new.propose_time, resolve_time = new.resolve_time,
        status = new.status, `type` = new.`type`, original_type = new.original_type,
        sprint_id = new.sprint_id, project_id = new.project_id,
        story_key = new.story_key, verify_note = new.verify_note,
        is_repeated = new.is_repeated, is_occasional = new.is_occasional,
        last_editor = new.last_editor, last_edit_time = new.last_edit_time,
        bounce_count = new.bounce_count, rdm_key = new.rdm_key
""")


# 图片行按 (doc_bug_key, seq) 幂等覆盖。seq 是「该故障内第几张」,重导后图片数变少时
# 旧的高序号行会残留,故导入前先按 key 删干净(见 _sync_doc_bug_images)。
UPSERT_DOC_BUG_IMAGE_SQL = text("""
    INSERT INTO rdm_doc_bug_image
        (doc_bug_key, seq, column_label, source_name, mime_type, byte_size,
         width, height, sha256, thumb_mime, thumb_byte_size, `data`, thumb)
    VALUES
        (:doc_bug_key, :seq, :column_label, :source_name, :mime_type, :byte_size,
         :width, :height, :sha256, :thumb_mime, :thumb_byte_size, :data, :thumb)
    AS new
    ON DUPLICATE KEY UPDATE
        column_label = new.column_label, source_name = new.source_name,
        mime_type = new.mime_type, byte_size = new.byte_size,
        width = new.width, height = new.height, sha256 = new.sha256,
        thumb_mime = new.thumb_mime, thumb_byte_size = new.thumb_byte_size,
        `data` = new.`data`, thumb = new.thumb
""")

DELETE_DOC_BUG_IMAGES_SQL = text(
    "DELETE FROM rdm_doc_bug_image WHERE doc_bug_key IN :keys"
).bindparams(bindparam("keys", expanding=True))


def _spool_upload(file: UploadFile, suffix: str = ".xlsx") -> tuple[str, int]:
    """把上传流分块写进临时文件,返回 (路径, 字节数)。调用方负责删除。

    ⚠ 同步函数(2026-09-17):读的是 `file.file`(Starlette 已落盘的 SpooledTemporaryFile)
      而不是 `await file.read()`。这样 upload/validate 两个路由可以是同步 `def`,
      由 FastAPI 丢进线程池执行 —— 解析几百 MB 的 xlsx、逐张解码截图都是**同步重活**,
      写在 `async def` 里会独占事件循环,把全服其它接口一起卡住(实测这份 297MB 的源表
      解析 + 生成缩略图要数秒到数十秒)。
    ⚠ 分块读仍然保留:整文件 read() 进内存会让峰值随截图数量线性涨。
    ⚠ suffix 由调用方给(2026-09-18 加):文档故障是 .xlsx,文档测试用例是 .csv,
      落盘后缀只影响临时文件本身的形态,但写死 .xlsx 会让排查时对不上源文件。
    """
    fd, path = tempfile.mkstemp(prefix="docbug-", suffix=suffix)
    total = 0
    try:
        with os.fdopen(fd, "wb") as fp:
            while True:
                chunk = file.file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大(>{MAX_UPLOAD_BYTES} 字节)",
                    )
                fp.write(chunk)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path, total


def _load_sprint_map(session) -> dict[str, dict[str, str]]:
    """归一化迭代名 → {sprint_id, sprint_name, project_id}（全库）。

    刻意加载**全库**而不是只加载目标项目:这样「名字拼错」和「属于别的项目」是
    两类可区分的跳过原因 —— 前者要去改 Excel,后者换个项目再导一次就行。
    """
    rows = session.execute(text("""
        SELECT sprint_id, sprint_name, project_id
        FROM rdm_sprint
    """)).fetchall()

    mapping: dict[str, dict[str, str]] = {}
    for sprint_id, sprint_name, proj_id in rows:
        norm = normalize_sprint_name(sprint_name)
        if norm:
            mapping[norm] = {
                "sprint_id": str(sprint_id),
                "sprint_name": sprint_name,
                "project_id": str(proj_id) if proj_id else "",
            }
    return mapping


def evaluate_doc_bug_rows(
    session,
    headers: list[str],
    data_rows: list[tuple[int, list[str]]],
    project_id: str,
    *,
    strict: bool,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """源表的读取结果 → 逐行判定结论。**导入与导入前校验共用的唯一实现。**

    分成两份实现是这次最容易犯的错:校验报告说"42 行可导入"、真导入却进去 43 行
    (或反过来),用户只能靠肉眼比对两份报告发现。故两边的差异**只允许有一个**:
    strict —— 校验走 True(启用 6 个必填列空值校验),导入走 False(保持原行为)。
    ⚠ 故事号曾列入 strict 口径(2026-09-17),校验会拦下故事号为空 / 拼不上
      issue_key 的行;用户 2026-09-18 拍板取消 —— 现在两路径都不再校验故事号,
      仅在结果行里透传原值供 DOC 详情弹窗展示。

    返回结构刻意与上传接口的响应同形(total_count/skipped/errors/valid_rows…),
    前端于是可以拿同一套渲染逻辑展示"校验报告"和"导入结果",不必写两份。

    sprint_id: 2026-09-19 新增。非空时把本次范围从「整个项目」**再收窄到这一个迭代**:
      行的 sprint 归一化后能匹配到迭代、且属于 project_id,但 sprint_id 不是它 ⇒ 跳过。
      空/None 表示不按迭代收窄(纯项目口径),保留给直接调用本函数的测试与脚本;
      两个 HTTP 端点都**强制要求**传(见 upload_doc_bugs),界面不存在"不选迭代"的路径。
      ⚠ 为什么按归一化后的 sprint_id 比而不是比原文:表里的 sprint 是人手写的迭代名,
        与 rdm_sprint.sprint_name 常有一字之差(`RobotClaw-Sprint 2` vs `RobotClaw-Sprint2`),
        拿原文比会把整批行判成"不属于本迭代" —— 用户看着迭代明明选对了却一行都导不进去。

    ⚠ 判定的**顺序**有语义,不要随意调换:
      先按 sprint 把不属于本次项目的行排除,再做字段校验。
      反过来先校验的话,一份含多个项目行的表会把"属于别的项目"的行也报成
      "故事号为空"之类 —— 而用户根本不该为那些行负责(换项目导即可)。
      sprint 收窄放在项目判定**之后**同理:先确认"这行是本次项目的",才有"是不是本次迭代的"
      这个更细的问题;顺序反了,别的项目的行会被报成"不属于本迭代",指向错误的修法。
    """
    cols = {f: find_column_index(headers, aliases) for f, aliases in COLUMN_ALIASES.items()}

    missing = [label for f, label in REQUIRED_COLUMNS.items() if cols[f] is None]
    if missing:
        return {
            "ok": False,
            "reason": "缺列",
            "errors": [
                f"表头缺少必要列: {'、'.join(missing)}。"
                f"实际读到 {len(headers)} 列（{'、'.join(h for h in headers if h)}）"
            ],
            "total_count": len(data_rows),
            "importable": 0,
            "valid_rows": [],
            "skipped": {},
            "sprints": [],
        }

    sprint_map = _load_sprint_map(session)
    # 只在校验模式下花这笔钱:导入路径的判定不依赖故事号,拉全表索引纯属浪费。
    story_index = _load_story_index(session) if strict else None

    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[str] = []
    # 跳过原因按 sprint 原值聚合 —— 逐行报会把「同一批 27 行都因为项目不对」
    # 刷成 27 条噪音,聚合后是一句「该 sprint 属于项目 X,已跳过 27 行」。
    skipped_by_sprint: dict[str, dict[str, Any]] = {}
    skipped_no_sprint = 0
    covered: dict[str, dict[str, Any]] = {}
    # 校验模式专用:按原因聚合的计数。errors 只回吐前 50 条,而"还剩多少行同类问题"
    # 是用户判断要不要回源头改表的关键 —— 40 行故事号为空只看到 50 条上限里的前几条
    # 会误判成零星问题。
    invalid_by_field: dict[str, int] = {}
    # sheet 行号(1-based) → 故障编码。截图归属要靠它把 drawing 锚点反算回行:
    # 调包方只放「本次真正导入」的行进来,于是无 sprint / 异项目的图片天然被排除,
    # 与本表的存留范围严格一致。读取侧的 row_no 就是物理行号(表头是第 1 行),
    # 与锚点行的换算 `from_row + 1` 同一坐标系 —— 错位一个都会静默挂错图。
    key_by_sheet_row: dict[int, str] = {}

    def mark_skip(raw: str, reason: str, kind: str) -> None:
        """记一条按 sprint 原值聚合的跳过。

        ⚠ kind 是**分桶的机器可读来源**，不是装饰。原先的分桶靠 `reason.startswith("属于项目")`
          这类字符串前缀反推，加一个原因就得回去改那段推导，且新原因的文案稍不留意就会被
          归进邻桶（新增的「不属于本次选择的迭代」若以「属于」起头，就会被算成 other_project）。
          reason 仍是给人看的，kind 是给计数用的，两者不要再合并。
        """
        slot = skipped_by_sprint.setdefault(raw, {"reason": reason, "kind": kind, "count": 0})
        slot["count"] += 1

    for row_no, values in data_rows:
        sprint_idx = cols["sprint_name"]
        sprint_raw = values[sprint_idx] if sprint_idx is not None and sprint_idx < len(values) else ""
        sprint_raw = (sprint_raw or "").strip()
        if not sprint_raw:
            skipped_no_sprint += 1
            continue

        sprint = sprint_map.get(normalize_sprint_name(sprint_raw))
        if sprint is None:
            mark_skip(sprint_raw, "在 rdm_sprint 中匹配不到同名迭代", "unknown_sprint")
            continue
        if sprint["project_id"] != project_id:
            mark_skip(
                sprint_raw,
                f"属于项目 {sprint['project_id']}, 不是本次选择的项目",
                "other_project",
            )
            continue
        # ── 本次迭代之外的行的归属:跳过,不是错误(2026-09-19)──────────────────
        # 一份「问题明细表」本来就把多个迭代的行混在一起,用户按迭代分几次导入。
        # 故这里的措辞是"不在本次范围内",与字段校验失败(errors)严格区分:
        # 前者不需要改表,换一个迭代再导一次即可;后者要回源头补值。
        if sprint_id and sprint["sprint_id"] != sprint_id:
            mark_skip(sprint_raw, "不属于本次选择的迭代", "other_sprint")
            continue

        row, err = build_doc_bug_row(
            values,
            cols,
            story_index=story_index,
            sprint_id=sprint["sprint_id"],
        )
        if err is not None:
            if len(invalid_rows) < MAX_REPORTED_ERRORS:
                invalid_rows.append(f"第{row_no}行: {err}")
            # 原因里的值每次不同(`[故事号] '4068' …`),聚合只取方括号里的字段名
            field = err.split("]")[0].lstrip("[") if err.startswith("[") else "其它"
            invalid_by_field[field] = invalid_by_field.get(field, 0) + 1
            continue

        row["sprint_id"] = sprint["sprint_id"]
        row["project_id"] = sprint["project_id"]
        valid_rows.append(row)
        key_by_sheet_row[row_no] = row["key"]

        slot = covered.setdefault(sprint["sprint_id"], {
            "sprint_id": sprint["sprint_id"],
            "sprint_name": sprint["sprint_name"],
            "count": 0,
        })
        slot["count"] += 1

    if skipped_no_sprint:
        skipped_by_sprint.setdefault(
            "", {"reason": "[sprint]为空", "kind": "no_sprint", "count": 0}
        )
        skipped_by_sprint[""]["count"] += skipped_no_sprint

    def _count_kind(kind: str) -> int:
        return sum(s["count"] for s in skipped_by_sprint.values() if s.get("kind") == kind)

    other_project = _count_kind("other_project")
    other_sprint = _count_kind("other_sprint")
    unknown_sprint = _count_kind("unknown_sprint")

    return {
        "ok": True,
        "reason": None,
        "total_count": len(data_rows),
        "importable": len(valid_rows),
        "valid_rows": valid_rows,
        # 「未标注 sprint」不在这里 —— 它不是"跳过"，而是"本次范围之外"。见 skipped。
        "errors": invalid_rows,
        "invalid_detail": invalid_by_field,
        "skipped": {
            "no_sprint": skipped_no_sprint,
            "other_project": other_project,
            "unknown_sprint": unknown_sprint,
            # 2026-09-19:属于本项目、但不是本次所选迭代的行。只在传了 sprint_id 时可能非 0。
            "other_sprint": other_sprint,
            "invalid": sum(invalid_by_field.values()),
            "strikethrough": 0,   # 由 read_doc_bug_sheet 单独回传,此处不重复计
        },
        "skipped_by_sprint": skipped_by_sprint,
        "sprints": sorted(covered.values(), key=lambda s: s["sprint_name"] or ""),
        "key_by_sheet_row": key_by_sheet_row,
    }


def _sync_doc_bug_images(
    session,
    xlsx_path: str,
    sheet_name: str,
    key_by_sheet_row: dict[int, str],
) -> dict[str, Any]:
    """把源表「截图1/截图2」两列的内嵌图片同步进 rdm_doc_bug_image。

    调用时机 = 业务行**已提交之后**。这是取舍不是疏忽:截图是附属证据,一张图解码
    失败不该把 43 行业务数据一起回滚 —— 失败只如实上报原因,不阻断导入。

    sheet_name 由调用方从 read_doc_bug_sheet 的返回值原样转交(不是再取一次常量):
    文本读取在「问题明细表」缺失时会退用活动表,而这里的 drawing 定位必须按名命中,
    两边各自决定就会出现「文本照导、图片静默不导,理由还写着『源文件无内嵌图片』」。

    两条安全前提,各自对应一个「静默出错」场景:
      · 源文件里**没有** drawing ⇒ 完全不动图片表。否则重导一份不含截图的版本会
        悄悄抹掉库里已有的图,而且不报任何错。
      · 反之按**本次导入的 key** 先删后插 —— 重导后图片数变少时,旧的高 seq 行必须
        消失(ON DUPLICATE KEY UPDATE 只覆盖不删除,残留会永远挂着)。
    """
    result: dict[str, Any] = {
        "images": 0,
        "images_total_bytes": 0,
        "image_seconds": 0.0,
        "image_stats": {},
        "image_error": None,
        "image_skipped": None,
    }
    if not key_by_sheet_row:
        return result

    started = time.monotonic()
    try:
        has_img = has_drawing(xlsx_path, sheet_name)
    except Exception as e:  # noqa: BLE001
        logger.warning("探测内嵌图片失败,已跳过截图导入: %s", e)
        result["image_error"] = f"探测内嵌图片失败: {e!s}"
        return result

    if not has_img:
        logger.info("源文件未挂 drawing,保留库中已有截图")
        result["image_skipped"] = "源文件无内嵌图片,未改动已有截图"
        return result

    stats: dict[str, int] = {}
    keys = list(dict.fromkeys(key_by_sheet_row.values()))
    try:
        session.execute(DELETE_DOC_BUG_IMAGES_SQL, {"keys": keys})
        inserted = 0
        total_bytes = 0
        for img in iter_doc_bug_image_rows(
            xlsx_path, sheet_name, key_by_sheet_row, stats
        ):
            session.execute(UPSERT_DOC_BUG_IMAGE_SQL, img)
            inserted += 1
            total_bytes += img["byte_size"] + (img["thumb_byte_size"] or 0)
        session.commit()
    except Exception as e:  # noqa: BLE001
        session.rollback()
        logger.exception("截图写入失败(业务行已保留)")
        result["image_stats"] = stats
        result["image_seconds"] = round(time.monotonic() - started, 2)
        result["image_error"] = f"{e!s}"
        return result

    elapsed = round(time.monotonic() - started, 2)
    logger.info(
        "文档故障截图入库 %s 张 / %.1f KiB / %.1fs(统计 %s)",
        inserted,
        total_bytes / 1024,
        elapsed,
        stats,
    )
    result.update(
        images=inserted,
        images_total_bytes=total_bytes,
        image_seconds=elapsed,
        image_stats=stats,
    )
    return result


@router.post("/doc-bugs/upload")
def upload_doc_bugs(
    request: Request,
    project_id: str = Query(..., description="JIRA项目ID,决定本次导入的取值范围"),
    sprint_id: str = Query(..., description="所选迭代ID,只导入该迭代的行"),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user_from_header)
):
    """导入文档故障。迭代归属取自表内【sprint】列;不属于本次项目/本次迭代的行一律跳过。

    ⚠ sprint_id 是**必填**(2026-09-19 由界面流程改版引入):导入范围从"整个项目"收窄到
      "所选迭代"。做成必填而不是可选,是因为漏传时的行为恰恰是最坏的那种 —— 会把整个项目
      的行都导进来,界面看不出任何异常,只有事后对比行数才发现多导了几个迭代。
      一份「问题明细表」含多个迭代,按迭代分次导入是现在的正常用法。

    ⚠ **本接口的字段口径比 /doc-bugs/validate 宽松**(见 evaluate_doc_bug_rows 的
    strict 参数)。要"导入前先把源表的问题摊开给用户看"请先调那个接口 ——
    本接口只保证"能导的都导进去",不承担把关职责。

    返回 success=False 只在**一条都没导入**时出现。部分行的字段问题不再阻断整批
    (480 行的人工表里一行漏填不该让另外 42 行导不进来),它们会计入 skipped.invalid
    并在 errors 里给出行号与原因。

    【截图1】【截图2】两列的内嵌图片会随行入库(rdm_doc_bug_image),归属由 drawing
    锚点反算 —— 只有本次导入的行、其图片才入表。截图失败不影响上面的业务行,
    原因随 image_error 一起返回。

    ⚠ **同步 def,不是 async def**(2026-09-17 改):本接口全程是同步重活(落盘、openpyxl
    解析几百 MB、Pillow 逐张解码、逐张写库)。写成 async def 时这些调用都跑在事件循环
    线程上,一次导入会把**全服其它接口**卡住数秒到数十秒;写成 def 由 FastAPI 自动放进
    线程池,事件循环不再被占。DB session 也在同一个线程里创建与使用,不存在跨线程复用。
    """
    _require_xlsx(file)
    _reject_oversize_upload(request)

    tmp_path: str | None = None
    try:
        tmp_path, size = _spool_upload(file)

        try:
            headers, data_rows, strikethrough_rows, sheet_name = read_doc_bug_sheet(tmp_path)
        except HTTPException:
            raise
        except InvalidFileException as e:
            # 后缀对但内容不是 xlsx(改名过的 .xls、损坏包):给 400 而不是 500 ——
            # 这是用户能自己处理的一类问题,报错文案要能照做。
            raise HTTPException(
                status_code=400,
                detail=f"文件不是有效的 .xlsx（老版 .xls 请先另存为 .xlsx）: {e!s}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")

        if not data_rows:
            raise HTTPException(status_code=400, detail="Excel 文件中没有有效数据行")

        with get_session() as session:
            # strict=False:导入侧**保持改版前的宽松口径**,不新增拦截。
            # 6 个必填列的空值校验只在"导入前校验"里生效(见 evaluate_doc_bug_rows
            # 的 docstring);故事号两路径都先不做校验(2026-09-18 拍板),原值透传。
            ev = evaluate_doc_bug_rows(
                session, headers, data_rows, project_id, strict=False, sprint_id=sprint_id
            )

            if not ev["ok"]:
                raise HTTPException(status_code=400, detail=ev["errors"][0])

            valid_rows = ev["valid_rows"]
            invalid_rows = ev["errors"]
            skipped_by_sprint = ev["skipped_by_sprint"]
            summary = dict(ev["skipped"])
            summary["strikethrough"] = strikethrough_rows

            def skip_notes() -> list[str]:
                return [
                    f"[sprint] '{raw}' {slot['reason']}, 跳过 {slot['count']} 行"
                    for raw, slot in skipped_by_sprint.items()
                ]

            if not valid_rows:
                notes = skip_notes() + invalid_rows
                return {
                    "success": False,
                    "project_id": project_id,
                    "sprint_id": sprint_id,
                    "imported": 0,
                    "total_count": ev["total_count"],
                    "skipped": summary,
                    "errors": notes[:MAX_REPORTED_ERRORS] or ["没有任何一行属于本次选择的迭代"],
                    "sprints": [],
                }

            try:
                for row_data in valid_rows:
                    session.execute(UPSERT_DOC_BUG_SQL, row_data)
                session.commit()
            except Exception as e:
                session.rollback()
                raise HTTPException(status_code=500, detail=f"导入数据失败: {e!s}")

            # 业务行已落库,再补截图(失败只上报,不回滚上面这 43 行,见 _sync_doc_bug_images)
            # sheet_name 原样转交:文本与截图必须读**同一张** sheet(见 read_doc_bug_sheet 的说明)
            image_result = _sync_doc_bug_images(
                session, tmp_path, sheet_name, ev["key_by_sheet_row"]
            )

            return {
                "success": True,
                "project_id": project_id,
                "sprint_id": sprint_id,
                "imported": len(valid_rows),
                "total_count": ev["total_count"],
                "skipped": summary,
                "errors": (skip_notes() + invalid_rows)[:MAX_REPORTED_ERRORS],
                "sprints": ev["sprints"],
                "file_size": size,
                "images": image_result["images"],
                "images_total_bytes": image_result["images_total_bytes"],
                "image_seconds": image_result["image_seconds"],
                "image_stats": image_result["image_stats"],
                "image_error": image_result["image_error"],
                "image_skipped": image_result["image_skipped"],
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.post("/doc-bugs/validate")
def validate_doc_bugs(
    request: Request,
    project_id: str = Query(..., description="JIRA项目ID,决定本次校验的取值范围"),
    sprint_id: str = Query(..., description="所选迭代ID,只校验该迭代的行"),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user_from_header)
):
    """导入前校验:只读地跑一遍导入的全部判定,把问题摊开,不写任何一张表。

    存在的理由(也是它与 upload 的分工):
      upload 的判定是宽容的 —— 一行不合格就跳过那一行,整批照常写入。这在
      "480 行的人工表里漏填一行"的场景下是优点,但用在"先看看这份表行不行"上
      就成了缺点:用户拿到的是一个**已写入库的结果**,想改得先清空再重来。
      故这里把同一套判定(prepare/evaluate 共享实现)以 strict 口径跑一遍,
      只回结论。反复调、调完再决定导不导,零副作用。

    范围与 upload 严格一致:只审「有 sprint、属于 project_id、且就是 sprint_id 这个迭代」的行。
    否则一份含多项目行的表会把别的项目的行也报成"故事号为空",而用户不该为
    那些行负责 —— 换个项目再导即可。

    ⚠ sprint_id 必填,理由同 upload_doc_bugs:漏传 = 校验整个项目,而界面是在
      「选择 Sprint」之后才走到这一步的,静默放大范围只会让报告与实际导入对不上。

    ⚠ errors 里**始终**前置一段按 sprint 聚合的范围说明(不再是"一行都过不了时才带")。
      校验报告的核心问题已经从"这些行字段对不对"变成"这份表里有多少行属于我选的迭代"
      —— 命中 3 行、跳过 40 行时,若只说"校验通过 3 条",用户会以为剩下的 40 行导进去了。

    strict 相对 upload 多出的一项:
      1. 6 个必填列(自动编号 / sprint / 优先级 / 处理人 / 处理状态 / 问题类别)
         任一为空即拦。
      ⚠ 故事号曾在此口径下做"形态 → 存在 → 与本行 sprint 对应"三段校验,
        2026-09-18 取消 —— 不再因为故事号为空 / 拼不上 issue_key 而拦行,
        故事号原值照旧进入结果行。

    ⚠ 校验通过 ≠ 导入必然成功:校验与导入之间库里的 sprint/story 可能被同步任务改掉
      (rdm_sprint 会被 /reports/sprints 全量重写)。故 upload 侧保留自己的判定,
      不去信任前端传来的"校验已通过"。
    ⚠ 反过来也成立:**校验通过数 < 实际写入数**(strict 是宽松口径的真超集),
      前端因此不再拿 importable 当"将要写入几行"的承诺(见 DocBugImport.vue)。

    ⚠ 同步 def,理由同 upload_doc_bugs 的 docstring(解析重活不能占事件循环)。
    """
    _require_xlsx(file)
    _reject_oversize_upload(request)

    tmp_path: str | None = None
    try:
        tmp_path, size = _spool_upload(file)

        try:
            headers, data_rows, strikethrough_rows, _sheet = read_doc_bug_sheet(tmp_path)
        except HTTPException:
            raise
        except InvalidFileException as e:
            raise HTTPException(
                status_code=400,
                detail=f"文件不是有效的 .xlsx（老版 .xls 请先另存为 .xlsx）: {e!s}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")

        if not data_rows:
            raise HTTPException(status_code=400, detail="Excel 文件中没有有效数据行")

        with get_session() as session:
            ev = evaluate_doc_bug_rows(
                session, headers, data_rows, project_id, strict=True, sprint_id=sprint_id
            )

            summary = dict(ev["skipped"])
            summary["strikethrough"] = strikethrough_rows

            # 表头缺列是"整份文件不可用",与逐行问题不同级 —— 单列一个标记,
            # 前端据此直接出错误态,不必去 errors 里解析文案。
            header_missing = not ev["ok"]
            errors = list(ev["errors"])
            if not header_missing:
                # ⚠ 始终前置(2026-09-19 改),不再是"一行都过不了时才带"。
                # 报告要回答的第一个问题是"这份表里有多少行属于我选的迭代":
                # 命中 3 行、其余 40 行在别的迭代时,只报"校验通过 3 条"会让人
                # 以为 40 行也进去了。表头缺列时不带 —— 那种情况下面这些行根本没被判定过。
                errors = [
                    f"[sprint] '{raw}' {slot['reason']}, 跳过 {slot['count']} 行"
                    for raw, slot in ev["skipped_by_sprint"].items()
                ] + errors

            return {
                "success": True,
                "project_id": project_id,
                "sprint_id": sprint_id,
                "header_ok": ev["ok"],
                "total_count": ev["total_count"],
                # 「本次范围内能过校验的行数」——不是最终写入数,但两者应恒等
                "importable": ev["importable"],
                # 审了但没有一行合格 = 这份表当前导不进来
                "valid": ev["ok"] and ev["importable"] > 0,
                "skipped": summary,
                # 逐行问题清单(含行号),上限 MAX_REPORTED_ERRORS 条
                "errors": errors[:MAX_REPORTED_ERRORS],
                # 按字段聚合的问题行数 —— 逐条清单会被上限截断,
                # 而"一共多少行同类问题"才是用户判断要不要回源头改表的依据
                "invalid_detail": ev["invalid_detail"],
                "sprints": ev["sprints"],
                "file_size": size,
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ============================================================
# 文档测试用例导入
# ============================================================
# 数据源:Jira 测试用例导出 CSV(docs/testset.csv)。
# 向导五步(2026-09-18 二改):选择项目 → 上传文档 → 数据校验 → 检查已有数据 → 执行导入。
# 原先由用户手选 Sprint,**现改为由故事号反查迭代**(用户拍板)。
#
# ★ 迭代归属的权威口径 = `rdm_issue`(不是用户选的,也不是写死的):
#     故事号 → rdm_issue.issue_key → rdm_issue.sprint_id / sprint_name
#   与两处既有实现同源,改这个模块前先认这一点:
#     · 报表「用例覆盖率」就是这么 join 的(reports.py: rdm_testcase.story_key
#       ∩ rdm_issue.issue_key);
#     · 同步侧写 rdm_testcase 时,sprint_id 取的是「当时正在同步的那个迭代」
#       (util/jira.py 的 Sprint.testcases),即**用例所属故事所在的迭代**。
#   ⚠ 别拿 rdm_testcase 自己的 sprint_id 反推归属:reports.py 的注释已写明它会停在
#     旧迭代(故事挪迭代后,同步侧只按用例自身的 refs 清理,不回头改旧行)。
#
# ★ 校验与导入**共用 evaluate_testcase_import(),刻意没有 strict 开关** ——
#   与「文档故障导入」相反(那边校验严、导入宽是拍板过的取舍)。理由:用户要求
#   「故事号解析不到就整份拒绝」,两侧判定必须逐字一致,否则会冒出「校验通过却导不
#   进去」这种把刻意不精确的数当承诺的界面文案。
#
# 三处结构性差异,每一条都对应一个会让数据静默变形的坑:
#   1. **源文档一行 ≠ 一个用例。** synapseRT 的步骤是「用例首行 + N 行后续步骤」:
#      只有首行有【关键字】,后续步骤行的前 154 列全空、只填步骤ID/步骤/期望结果。
#      故必须先按【关键字】向下归并成用例,再把 N 行折成 steps JSON —— 否则一份
#      3 行的文档会被读成「3 个用例,其中 2 个没有编号」。
#   2. **源文档没有 Jira 数字 issue id。** rdm_testcase 的唯一键是 (case_id, story_key),
#      而同步侧存的 case_id 是 Jira 数字 id(实测 '611885',case_key 是 'CMP-2168')。
#      这里**拿 case_key 顶替** case_id:不能用 NULL —— MySQL 唯一索引把 NULL 视作
#      互不相同,重导同一份文档会不断追加重复行,幂等直接失效。
#   3. **故事号必须能在 rdm_issue 里查到,否则整份文件拒绝**(用户 2026-09-18 拍板)。
#      查不到就没有迭代归属,而用例的所有统计口径都按 sprint_id 过滤
#      (reports.py 的用例数 = COUNT(DISTINCT case_id) WHERE sprint_id = ?)——
#      放行等于写一批**在界面上完全隐形**的行,比直接报错更难排查。
#      ⚠ 实测这份文档引用的 EMBODIED_ADP-4094 当前就查不到(Botadp-Sprint-13 尚未同步),
#        故**同步对应迭代之前,这份文档会被整份拒绝** —— 这是预期行为,不是 bug。
#      ⚠ 同理,解出的迭代若属于**别的项目**也拒绝:否则会把用例挂到另一个项目的迭代上,
#        而这类错挂没有任何界面看得出来(列表按 project_id 过滤,两边都不显示异常)。
#
# ⚠ **写入目标是 rdm_testcase —— 与 RDM 同步任务共表**(用户 2026-09-18 拍板)。
#   由此带来两条必须记住的后果,改这个模块前先读:
#   · 「清空」已按**本次文档的故事号**精确删(2026-09-18 二改),不再按迭代/整项目删
#     —— 共用表没有来源列,唯一能框住「本次导入」的维度就是文档自己引用了哪些故事;
#   · 同步任务若日后带回同一用例的数字 case_id,同一用例会变成两行(它按 case_id 清理,
#     不认我们的 case_key),届时 COUNT(DISTINCT case_id) 会重复计数。这不是 bug,
#     是选此方案的已知代价 —— 换成独立表可以根治,但那要改报表口径。

TESTCASE_COLUMN_ALIASES: dict[str, list[str]] = {
    "case_key": ["关键字"],
    "case_name": ["概要"],
    # 源文档没有用例状态列(库里同步侧写的是 Jira status,如「待办」)→ 落 NULL,不猜。
    "status": ["状态"],
    "exec_status": ["最新结果", "执行状态"],
    # ⚠ module 取【测试用例集】而不是【模块】:同步侧的 module 存的是 customfield_11102,
    #   该字段在库里的实际值是「数据采集平台md-dc-sp1测试用例集」这种**用例集名**
    #   (见 rdm_testcase 现有 1351 行);而 Jira 标准「模块」列在这份导出里是空的。
    #   两者都留作别名,顺序即优先级。
    "module": ["测试用例集", "模块"],
    "story_key": ["需求"],
    "labels": ["标签"],
    "description": ["描述"],
    "step_no": ["步骤ID", "#"],
    "step_action": ["步骤"],
    "step_data": ["测试数据"],
    "step_expected": ["期望结果"],
}

# 列级必填(表头里必须有)。缺一即整份文件不可用。
# ⚠ 【需求】为什么算必填:它是用例与故事的唯一关联,报表的「用例覆盖率」就靠它
#   (reports.py 用 rdm_testcase.story_key ∩ rdm_issue.issue_key)。没有它,导进去的
#   用例只会推高「用例数」、永远进不了覆盖率,还查不出原因。
# ⚠ 值层面的校验**要做**(2026-09-18 二改,推翻一改时的「透传不校验」):
#   每个故事号都必须在 rdm_issue 里查得到,否则**整份文件拒绝**。
#   一改之所以不做,是因为当时迭代由用户手选、故事号查不到也不影响落库;
#   现在迭代归属改由故事号反查,查不到就等于没有归属 —— 见 evaluate_testcase_import。
TESTCASE_REQUIRED_COLUMNS: dict[str, str] = {"case_key": "关键字", "story_key": "需求"}

# CSV 解码编码的试探顺序。utf-8-sig 放第一位是为了**吃掉 BOM** —— 否则第一个表头
# 会变成 `\ufeff关键字`,列找不到、整份文件报「缺列」,而肉眼看着明明有这一列。
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gbk")


def _require_csv(file: UploadFile) -> None:
    """只接受 .csv(2026-09-18,用户拍板)。

    ⚠ 与前端 DocTestcaseImport.vue 的 accept/正则同口径,改一处要同步另一处。
    ⚠ 大小写不敏感,理由同 _require_xlsx。
    """
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="仅支持 .csv 格式")


def read_testcase_csv(path: str) -> tuple[list[str], list[tuple[int, list[str]]], str]:
    """CSV → (表头, [(行号, 各列文本)], 实际使用的编码)。

    ⚠ 编码必须**真解一遍**再定,不能只看 BOM:Jira 导出是带 BOM 的 UTF-8,而同一份表
      被用户用中文 Windows 的 Excel 另存成 CSV 后是 GBK —— 两种都会出现在真实工单里。
      GBK 字节流按 utf-8 解码会抛 UnicodeDecodeError(不是变成乱码),故试探是可靠的。

    ⚠ 多行折行(描述里带换行)由 csv 模块处理:它是 quoted 字段,`csv.reader` 天然
      按引号配对切行。**不能用 `readlines()` 或按 \n split** —— 那样一份 3 个用例的
      文档会被切出 5+ 行,且行号与 Excel 里看到的完全对不上。
    """
    with open(path, "rb") as fp:
        raw = fp.read()

    decoded: str | None = None
    used_encoding = ""
    for enc in CSV_ENCODINGS:
        try:
            decoded = raw.decode(enc)
            used_encoding = enc
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise HTTPException(status_code=400, detail="CSV 编码无法识别(已尝试 utf-8 / gbk)")

    rows = list(csv.reader(io.StringIO(decoded)))
    if not rows:
        return [], [], used_encoding

    headers = [cell_text(h) for h in rows[0]]
    data_rows: list[tuple[int, list[str]]] = []
    for idx, row in enumerate(rows[1:], start=2):
        values = [cell_text(v) for v in row]
        if not any(values):
            continue  # 尾部空行:不计入总数
        data_rows.append((idx, values))
    return headers, data_rows, used_encoding


def build_testcase_cases(
    headers: list[str],
    data_rows: list[tuple[int, list[str]]],
) -> dict[str, Any]:
    """CSV 读取结果 → **按用例归并**后的候选集。只做解析与结构校验,不碰数据库。

    归并规则(顺序有语义):
      · 【关键字】非空 ⇒ 开一个新用例(首行的步骤列属于它);
      · 【关键字】为空且有步骤内容 ⇒ 续到当前用例(步骤行);
      · 【关键字】为空、也没有步骤内容 ⇒ 既不是用例也不是步骤,计入 no_case_key 并报行号
        —— 这类行最可能是「用户删了关键字想手改」,静默丢弃会让人以为文档只有一半;
      · 首个用例之前出现的步骤行 ⇒ orphan_step(没有可以挂靠的用例)。

    ⚠ 同一个【关键字】出现多个块时**合并**而不是后者覆盖前者(步骤按出现顺序拼接、
      需求取并集):直接按 upsert 覆盖会让前一块的步骤静默消失,而幂等正是靠
      「一个用例一行」保证的。

    ⚠ 需求取并集后**展开成多行**(每 (case_key, story_key) 一行),这是刻意的:
      rdm_testcase 的唯一键就是 (case_id, story_key),同步侧一个用例引用多个故事时
      也是这么落的(见 report_rdm_data._write_testcases)。

    返回结构 (消费方见 upload_testcases):
      ok / errors / total_rows / cases:[{...,"story_keys":[...],"refs_note"}] /
      skipped:{orphan_step,no_case_key,no_story,empty_step} / case_sets / step_count
    """
    cols = {f: find_column_index(headers, aliases) for f, aliases in TESTCASE_COLUMN_ALIASES.items()}

    missing = [label for f, label in TESTCASE_REQUIRED_COLUMNS.items() if cols[f] is None]
    if missing:
        return {
            "ok": False,
            "errors": [
                f"表头缺少必要列: {'、'.join(missing)}。"
                f"实际读到 {len(headers)} 列（{'、'.join(h for h in headers if h)}）"
            ],
            "total_rows": len(data_rows),
            "cases": [],
            "skipped": {},
            "case_sets": [],
            "step_count": 0,
        }

    def value(values: list[str], field: str) -> str:
        idx = cols.get(field)
        if idx is None or idx >= len(values):
            return ""
        return values[idx]

    ordered: list[str] = []
    blocks: dict[str, dict[str, Any]] = {}
    skipped = {"orphan_step": 0, "no_case_key": 0, "no_story": 0, "empty_step": 0}
    errors: list[str] = []
    current: dict[str, Any] | None = None

    def note(msg: str) -> None:
        if len(errors) < MAX_REPORTED_ERRORS:
            errors.append(msg)

    for row_no, values in data_rows:
        case_key = value(values, "case_key")

        # ── 步骤行:折进当前用例 ──
        step_no = value(values, "step_no")
        step_action = value(values, "step_action")
        step_data = value(values, "step_data")
        step_expected = value(values, "step_expected")
        has_step = bool(step_action or step_data or step_expected)

        if not case_key:
            if has_step:
                if current is None:
                    skipped["orphan_step"] += 1
                    note(f"第{row_no}行: 步骤内容出现在任何用例之前,没有可归属的用例,已跳过")
                    continue
                steps = current["steps"]
                steps.append({
                    "no": step_no or str(len(steps) + 1),
                    "action": step_action,
                    "data": step_data,
                    "expected": step_expected,
                })
                continue
            skipped["no_case_key"] += 1
            note(f"第{row_no}行: [关键字]为空且没有步骤内容,已跳过")
            continue

        # ── 用例首行:新建或合并到同名块 ──
        block = blocks.get(case_key)
        if block is None:
            block = {
                "case_key": case_key,
                "case_name": value(values, "case_name"),
                "status": value(values, "status") or None,
                "exec_status": value(values, "exec_status") or None,
                "module": value(values, "module") or None,
                "labels": value(values, "labels") or None,
                "description": value(values, "description") or None,
                "story_keys": [],
                "steps": [],
            }
            blocks[case_key] = block
            ordered.append(case_key)

        story_key = value(values, "story_key")
        if story_key and story_key not in block["story_keys"]:
            block["story_keys"].append(story_key)

        if has_step:
            block["steps"].append({
                "no": step_no or str(len(block["steps"]) + 1),
                "action": step_action,
                "data": step_data,
                "expected": step_expected,
            })
        elif step_no:
            # 只有步骤ID、没有任何内容:synapseRT 导出会长出这种空壳行,计数但不报错
            skipped["empty_step"] += 1

        current = block

    # ── 块 → 入库行(一个故事一行)──
    cases: list[dict[str, Any]] = []
    case_sets: dict[str, int] = {}
    step_count = 0
    for case_key in ordered:
        block = blocks[case_key]
        story_keys = block.pop("story_keys")
        steps = block.pop("steps")
        if not story_keys:
            skipped["no_story"] += 1
            note(f"用例 {case_key}: [需求]为空,无法关联故事,该用例已跳过")
            continue
        block["steps_json"] = json.dumps(steps, ensure_ascii=False) if steps else None
        block["step_count"] = len(steps)
        block["refs"] = story_keys
        step_count += len(steps)
        if block["module"]:
            case_sets[block["module"]] = case_sets.get(block["module"], 0) + 1
        for story_key in story_keys:
            cases.append({**block, "story_key": story_key})

    return {
        "ok": True,
        "errors": errors,
        "total_rows": len(data_rows),
        "cases": cases,
        "skipped": skipped,
        "case_sets": sorted(
            ({"name": k, "count": v} for k, v in case_sets.items()),
            key=lambda x: -x["count"],
        ),
        "step_count": step_count,
    }


# ── 故事号 → 迭代归属(权威口径见本节开头的 ★)──────────────────────────
TESTCASE_STORY_SPRINT_SQL = text("""
    SELECT i.issue_key, i.sprint_id, i.sprint_name,
           s.project_id, s.project_name, s.state
    FROM rdm_issue i
    LEFT JOIN rdm_sprint s ON s.sprint_id = i.sprint_id
    WHERE i.issue_key IN :keys
""").bindparams(bindparam("keys", expanding=True))

# 同一故事号跨迭代留行时,优先取「还没结束」的那个迭代,再以 sprint_id 降序兜底。
# 实测 rdm_issue 里确有 5 个 issue_key 跨 2 个迭代(如 CMP-397 同时在 5388 / 5470):
# 同步是「按 sprint 增量写 + 只清本迭代旧行」,故事被挪到新迭代后旧行会留在原迭代。
# ⚠ 这不是"取最新"的猜测,而是"取它现在真正所在的迭代":active > future > closed,
#   同档取 sprint_id 最大者 —— 两把尺子都是确定的,保证同一份输入永远解出同一个结果。
TESTCASE_SPRINT_STATE_RANK = {"active": 2, "future": 1}


def resolve_testcase_sprints(
    session, story_keys: list[str]
) -> tuple[dict[str, dict], list[str]]:
    """故事号 → 迭代归属。返回 (resolved, missing)。

    resolved: {story_key: {sprint_id, sprint_name, project_id, project_name, state}}
    missing : 在 rdm_issue 里一条都查不到的故事号(升序,便于稳定报错)

    ⚠ 只查一次(IN 展开),不要按 key 逐个查 —— 一份文档几百个故事号时会变成几百次往返。
    """
    keys = sorted({k for k in story_keys if k})
    if not keys:
        return {}, []
    rows = session.execute(TESTCASE_STORY_SPRINT_SQL, {"keys": keys}).fetchall()

    best: dict[str, tuple[tuple[int, str], dict]] = {}
    for issue_key, sprint_id, sprint_name, project_id, project_name, state in rows:
        rank = (TESTCASE_SPRINT_STATE_RANK.get(state or "", 0), str(sprint_id or ""))
        if issue_key not in best or rank > best[issue_key][0]:
            best[issue_key] = (rank, {
                "sprint_id": str(sprint_id) if sprint_id is not None else None,
                "sprint_name": sprint_name,
                "project_id": str(project_id) if project_id is not None else None,
                "project_name": project_name,
                "state": state,
            })
    return {k: v[1] for k, v in best.items()}, [k for k in keys if k not in best]


def evaluate_testcase_import(
    session,
    *,
    project_id: str,
    headers: list[str],
    data_rows: list[tuple[int, list[str]]],
    now,
) -> dict[str, Any]:
    """校验与导入的**唯一共享实现**(刻意没有 strict 开关,理由见本节开头 ★)。

    只做「解析 → 归属解析 → 组装入库行」,**一次库都不写**;写库是调用方的事。
    返回:
      fatal           : True ⇒ 整份文件不可导入(调用方直接 400 / 渲染成错误态)
      ok              : 表头是否齐备(与 fatal 分开:表头不齐时连行都读不了)
      rows            : 待写入的行(每个「用例 × 故事」一行);fatal 时为 []
      case_refs       : {case_key: [story_key, ...]} 供调用方清理旧行(与同步侧同规则)
      stories         : 本次覆盖的故事号及其迭代归属
      missing_stories : 查不到的故事号(fatal 的原因之一)
      errors / skipped / total_rows / case_count / step_count / case_sets / encoding 等
    """
    built = build_testcase_cases(headers, data_rows)
    errors: list[str] = list(built["errors"])
    skipped = dict(built["skipped"])
    result: dict[str, Any] = {
        "project_id": project_id,
        "ok": built["ok"],
        "fatal": True,
        "total_rows": built["total_rows"],
        "case_count": 0,
        "step_count": built["step_count"],
        "skipped": skipped,
        "case_sets": [],
        "rows": [],
        "case_refs": {},
        "stories": [],
        "missing_stories": [],
        "errors": errors,
    }

    if not built["ok"]:
        return result

    cases = built["cases"]
    if not cases:
        errors.append("没有任何一行同时具备【关键字】与【需求】")
        return result

    story_keys = [c["story_key"] for c in cases]
    resolved, missing = resolve_testcase_sprints(session, story_keys)
    story_case_count: dict[str, int] = {}
    for c in cases:
        story_case_count[c["story_key"]] = story_case_count.get(c["story_key"], 0) + 1
    # ⚠ stories / case_count / case_sets 在 fatal 判定**之前**就填好:整份被拒时,用户最
    #   需要看到的恰恰是「哪些故事号解出来了、落到哪个迭代、哪些没解出来」——
    #   只回一张错误清单,等于把有用的那半边藏起来。
    result["missing_stories"] = missing
    result["case_count"] = len({c["case_key"] for c in cases})
    result["case_sets"] = built["case_sets"]
    result["stories"] = [
        {
            "story_key": k,
            "sprint_id": resolved[k]["sprint_id"],
            "sprint_name": resolved[k]["sprint_name"],
            "project_id": resolved[k]["project_id"],
            "project_name": resolved[k]["project_name"],
            "state": resolved[k]["state"],
            "case_count": story_case_count.get(k, 0),
        }
        for k in sorted(resolved)
    ]

    # ── 一票否决的三条(任意一条成立即整份拒绝)──
    if skipped.get("no_story"):
        errors.append(
            f"{skipped['no_story']} 个用例的【需求】(故事号)为空 —— 没有故事号就没有迭代归属,"
            "请回源文档补齐后再导"
        )
    if missing:
        shown = "、".join(missing[:10])
        tail = f" 等 {len(missing)} 个" if len(missing) > 10 else ""
        errors.append(
            f"以下故事号在 rdm_issue 中不存在:{shown}{tail}。"
            "调迭代归属靠故事号反查,查不到就无法确定落在哪个迭代 —— "
            "请先同步这些故事所在的迭代,再重新导入"
        )
    # 迭代属于别的项目 ⇒ 会把用例挂到另一个项目的迭代上,而没有任何界面看得出异常
    foreign = sorted({
        f"{r['project_id'] or '未知项目'}({k})"
        for k, r in resolved.items()
        if r["project_id"] and r["project_id"] != project_id
    })
    if foreign:
        errors.append(
            f"以下故事号所属的迭代不属于本次选择的项目 {project_id}:"
            f"{'、'.join(foreign[:10])} —— 请切换到对应项目再导"
        )

    if skipped.get("no_story") or missing or foreign:
        return result

    # ── 组装入库行 ──
    rows: list[dict[str, Any]] = []
    case_refs: dict[str, list[str]] = {}
    for c in cases:
        info = resolved[c["story_key"]]
        case_refs.setdefault(c["case_key"], [])
        if c["story_key"] not in case_refs[c["case_key"]]:
            case_refs[c["case_key"]].append(c["story_key"])
        rows.append({
            "case_id": c["case_key"],   # 源文档无数字 issue id,用 case_key 顶替
            "case_key": c["case_key"],
            "case_name": c["case_name"],
            "status": c["status"],
            "exec_status": c["exec_status"],
            "module": c["module"],
            "story_key": c["story_key"],
            "labels": c["labels"],
            "description": c["description"],
            "steps": c["steps_json"],
            # sprint_* 来自故事;project_* 取解出的迭代所属项目。
            # ⚠ rdm_sprint 里查不到该 sprint 时(LEFT JOIN 为 NULL)project_* 回落到
            #   本次选择的项目 —— 此时无法交叉验证,但 sprint_id/sprint_name 仍来自
            #   rdm_issue,落库信息依旧完整。
            "sprint_id": info["sprint_id"],
            "sprint_name": info["sprint_name"],
            "project_id": info["project_id"] or project_id,
            "project_name": info["project_name"] or None,
            "created": None,   # 文档没有创建/更新时间,不编造
            "updated": now,
        })

    result.update({
        "fatal": False,
        "rows": rows,
        "case_refs": case_refs,
    })
    return result


def testcase_report(result: dict[str, Any], *, encoding: str, file_size: int) -> dict[str, Any]:
    """evaluate_testcase_import 的结果 → 接口响应(校验与导入**同形**,前端一套渲染)。

    ⚠ 不返回 rows/case_refs(几 MB 的入库行没有回给浏览器的理由),只回结论与证据。
    """
    return {
        "success": not result["fatal"],
        "valid": not result["fatal"],
        "project_id": result["project_id"],
        "header_ok": result["ok"],
        "total_rows": result["total_rows"],
        "case_count": result["case_count"],
        "step_count": result["step_count"],
        "importable": len(result["rows"]),
        "skipped": result["skipped"],
        "case_sets": result["case_sets"],
        "stories": result["stories"],
        "missing_stories": result["missing_stories"],
        "errors": result["errors"][:MAX_REPORTED_ERRORS],
        "encoding": encoding,
        "file_size": file_size,
    }


# 幂等写入:唯一键 (case_id, story_key) —— case_id 用 case_key 顶替(理由见本节开头)。
# ON DUPLICATE 里**不更新 created**:文档没有这个信息,插入时写的 NULL 不该在重导时
# 把同步任务写过的真实创建时间抹掉。
TESTCASE_UPSERT_SQL = text("""
    INSERT INTO rdm_testcase
        (case_id, case_key, case_name, status, exec_status, module, story_key,
         labels, description, steps, sprint_id, sprint_name, project_id,
         project_name, created, updated)
    VALUES
        (:case_id, :case_key, :case_name, :status, :exec_status, :module, :story_key,
         :labels, :description, :steps, :sprint_id, :sprint_name, :project_id,
         :project_name, :created, :updated)
    AS new
    ON DUPLICATE KEY UPDATE
        case_key = new.case_key, case_name = new.case_name,
        status = new.status, exec_status = new.exec_status,
        module = new.module, labels = new.labels,
        description = new.description, steps = new.steps,
        sprint_id = new.sprint_id, sprint_name = new.sprint_name,
        project_id = new.project_id, project_name = new.project_name,
        updated = new.updated
""")

# 用例改引其他故事时删掉旧行 —— 与 report_rdm_data._write_testcases 同一规则,
# 否则重导后「旧故事 + 新故事」两行并存,覆盖率会把一个已解绑的故事算成被覆盖。
DELETE_TESTCASE_STALE_SQL = text("""
    DELETE FROM rdm_testcase
    WHERE case_id = :case_id
    AND story_key NOT IN :refs
""").bindparams(bindparam("refs", expanding=True))


@router.post("/testcases/validate")
def validate_testcases(
    request: Request,
    project_id: str = Query(..., description="JIRA项目ID"),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user_from_header),
):
    """导入前校验:同一份文件、同一套判定,但**只读不写库**,可反复调用。

    与 upload 走同一个 evaluate_testcase_import(),故「校验通过」与「导得进去」必然
    一致 —— 不存在文档故障那边的 strict/宽松双口径:故事号解析不到就整份拒绝,
    连导入按钮都不该给。
    ⚠ 同步 def 而非 async def,理由同 upload_testcases(解析重活不能占事件循环)。
    """
    _require_csv(file)
    _reject_oversize_upload(request)

    tmp_path: str | None = None
    try:
        tmp_path, size = _spool_upload(file, suffix=".csv")
        try:
            headers, data_rows, encoding = read_testcase_csv(tmp_path)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")

        if not data_rows:
            raise HTTPException(status_code=400, detail="CSV 文件中没有有效数据行")

        with get_session() as session:
            evaluated = evaluate_testcase_import(
                session,
                project_id=project_id,
                headers=headers,
                data_rows=data_rows,
                now=now_beijing(),
            )
        return testcase_report(evaluated, encoding=encoding, file_size=size)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class ClearTestcasesRequest(BaseModel):
    """清空的范围 = **本次文档涉及的故事号**(用户 2026-09-18 拍板)。

    ⚠ 刻意**不接受**「整个项目」这种口径:sprint_id 入参已随「去掉选择 Sprint」一并移除,
      而共用表里没有来源列,唯一能框住「本次导入」的维度就是文档自己引用了哪些故事。
      story_keys 为空 ⇒ 400,把「误删整个项目」这条路直接堵死(实测数据工具链平台有 1351 行)。
    """

    project_id: str
    story_keys: list[str] = []


@router.delete("/testcases")
async def clear_testcases(
    request: ClearTestcasesRequest,
    current_user: dict = Depends(get_current_user_from_header),
):
    """删除「本次文档涉及的故事号」下的测试用例。

    ⚠⚠ **rdm_testcase 与 RDM 同步任务共表**,故这里的删除**不区分来源** —— 只要某条用例
      关联的故事号在本次文档里,就会一起删掉(含同步任务写入的那条)。这是选「共用一张表」
      方案的已知代价:表里没有 source 列。前端因此在确认框里必须写清删的是「故事号范围」,
      不能只说「清空本次导入的数据」。
    """
    story_keys = sorted({k for k in request.story_keys if k})
    if not story_keys:
        raise HTTPException(
            status_code=400,
            detail="未提供故事号,拒绝执行 —— 清空按「本次文档涉及的故事号」删除,空范围会导致整项目被清空",
        )

    with get_session() as session:
        try:
            result = session.execute(
                text("DELETE FROM rdm_testcase WHERE story_key IN :keys").bindparams(
                    bindparam("keys", expanding=True)
                ),
                {"keys": story_keys},
            )
            session.commit()
            return {"deleted": result.rowcount, "story_count": len(story_keys)}   # type: ignore[attr-defined]
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=500, detail=f"清除数据失败: {e!s}")


TESTCASE_SELECT_COLUMNS = """
    t.case_key, t.case_name, t.status, t.exec_status, t.module,
    t.story_key, t.labels, t.sprint_id, t.sprint_name,
    t.project_id, t.project_name, t.updated, t.steps
"""


def _testcase_row_to_item(row) -> dict[str, Any]:
    """一行 → 接口字典。

    ⚠ step_count 在 Python 侧数,不用 SQL 的 JSON_LENGTH:steps 是 mediumtext 且同步侧
      可能写入 None 或半截 JSON(`_test_steps` 失败即返回 None),`JSON_LENGTH` 遇到
      非 JSON 文本会**直接报错**整条查询,而这里只是少一个数字。
    """
    steps_raw = row[12]
    step_count = 0
    if steps_raw:
        try:
            parsed = json.loads(steps_raw)
            if isinstance(parsed, list):
                step_count = len(parsed)
        except (ValueError, TypeError):
            step_count = 0

    return {
        "case_key": row[0],
        "case_name": row[1],
        "status": row[2],
        "exec_status": row[3],
        "module": row[4],
        "story_key": row[5],
        "labels": row[6],
        "sprint_id": str(row[7]) if row[7] else None,
        "sprint_name": row[8],
        "project_id": str(row[9]) if row[9] else None,
        "project_name": row[10],
        "updated": row[11].isoformat() if row[11] else None,
        "step_count": step_count,
    }


@router.get("/testcases")
async def list_testcases(
    project_id: str = Query(..., description="JIRA项目ID"),
    story_keys: list[str] | None = Query(
        None, description="只返回这些故事号下的用例(本次文档涉及的故事);不传则返回该项目全部"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user_from_header),
):
    """列出已入库的测试用例 —— 「检查已有数据」那一步的数据源。

    ⚠ 结果里**包含 RDM 同步任务写入的行**,不只有文档导入的:表是共用的,没有来源列
      (见本节的方案说明)。前端提示文案必须说清这一点。
      ⚠ story_keys 收窄同样服务于这一点:去掉选 Sprint 后,「这份文档会不会重复导入」
        只能靠文档自己引用了哪些故事来界定,别再退回「按项目全量列」。
    """
    where = "t.project_id = :project_id"
    params: dict[str, Any] = {"project_id": project_id}
    keys = sorted({k for k in (story_keys or []) if k})
    if keys:
        where += " AND t.story_key IN :keys"
        params["keys"] = keys

    count_stmt = text(f"SELECT COUNT(*) FROM rdm_testcase t WHERE {where}")
    data_stmt = text(f"""
            SELECT {TESTCASE_SELECT_COLUMNS}
            FROM rdm_testcase t
            WHERE {where}
            ORDER BY t.case_key
            LIMIT :limit OFFSET :offset
        """)
    # ⚠ expanding bindparam **只在真拼了 `IN :keys` 时才挂**:无条件挂会在不带
    #   story_keys 的查询上抛 ArgumentError(doesn't define a bound parameter named 'keys')。
    if keys:
        count_stmt = count_stmt.bindparams(bindparam("keys", expanding=True))
        data_stmt = data_stmt.bindparams(bindparam("keys", expanding=True))

    with get_session() as session:
        total = session.execute(count_stmt, params).fetchone()[0]   # type: ignore[attr-defined]

        data_result = session.execute(
            data_stmt,
            {**params, "limit": page_size, "offset": (page - 1) * page_size})

        items = [_testcase_row_to_item(row) for row in data_result]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/testcases/upload")
def upload_testcases(
    request: Request,
    project_id: str = Query(..., description="JIRA项目ID"),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user_from_header),
):
    """导入文档测试用例(CSV)。

    与其他导入路径的分工:
      · 【关键字】相同的行归并成一个用例,步骤折成 steps JSON(键名与同步侧逐字一致:
        no / action / data / expected,见 util/jira.py 的 _test_steps);
      · **迭代归属由故事号反查**(不再由前端传 sprint_id):走 evaluate_testcase_import,
        与 /testcases/validate 是同一份实现 —— 校验说能导,这里就一定导得进去;
      · 故事号必须能在 rdm_issue 里查到、且所属迭代属于所选项目,否则**整份拒绝**;
        需求为空的用例同样拒绝 —— 唯一键 (case_id, story_key) 里 NULL 互不相等,
        写进去既没有迭代归属,也无法幂等重导。

    ⚠ 写入 rdm_testcase 前会按 case_id 清掉不再被引用的旧 story_key 行(与同步侧同规则),
      故「文档里把需求从 A 改成 B」这种改动能被正确反映,不会留下 A 的残留行。

    ⚠ 同步 def 而非 async def,理由同 upload_doc_bugs(解析重活不能占事件循环)。
    """
    _require_csv(file)
    _reject_oversize_upload(request)

    tmp_path: str | None = None
    try:
        tmp_path, size = _spool_upload(file, suffix=".csv")

        try:
            headers, data_rows, encoding = read_testcase_csv(tmp_path)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")

        if not data_rows:
            raise HTTPException(status_code=400, detail="CSV 文件中没有有效数据行")

        with get_session() as session:
            evaluated = evaluate_testcase_import(
                session,
                project_id=project_id,
                headers=headers,
                data_rows=data_rows,
                now=now_beijing(),
            )
            report = testcase_report(evaluated, encoding=encoding, file_size=size)
            if evaluated["fatal"]:
                # 整份拒绝:一条也不写。⚠ 刻意回 200 + success=false,而不是 400 ——
                # 报告要能被前端原样渲染(与 →validate 完全同形),塞进 HTTPException 的
                # detail 会被 axios 拦截器吃掉,用户只能看到一句话而不是那份原因清单。
                return report

            try:
                # 按用例清旧的 story_key 行(与同步侧同规则),再 upsert
                for case_key, refs in evaluated["case_refs"].items():
                    session.execute(
                        DELETE_TESTCASE_STALE_SQL,
                        {"case_id": case_key, "refs": refs},
                    )
                for row_data in evaluated["rows"]:
                    session.execute(TESTCASE_UPSERT_SQL, row_data)
                session.commit()
            except Exception as e:  # noqa: BLE001
                session.rollback()
                raise HTTPException(status_code=500, detail=f"导入数据失败: {e!s}")

        return {**report, "imported": len(evaluated["rows"])}

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"处理文件失败: {e!s}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
