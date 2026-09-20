import { get, post, del } from './index'

/**
 * 把磁盘上的 File 复制成一份「独立」的 File,绕开 Chromium 的
 * `ERR_UPLOAD_FILE_CHANGED` —— 直接把原始 File 放进 FormData 时,
 * XHR 会跟踪磁盘文件,期间被外部改动(OneDrive 同步 / 杀软扫描 /
 * Excel 仍持有文件等)就会被 abort,axios 端只看到一个 Network Error。
 *
 * 先读进 ArrayBuffer,再封装成新的 File,浏览器只看到内存里的字节,
 * 与磁盘原文件彻底解耦。297MB 的内嵌截图表实测无压力;
 * 若未来单文件逼近内存上限,再降级为直传(返回原 File)。
 */
async function detachedFile(file: File): Promise<File> {
  const buffer = await file.arrayBuffer()
  return new File([new Blob([buffer], { type: file.type })], file.name, { type: file.type })
}

export interface DocBugRecord {
  key: string | null
  name: string | null
  priority: string | null
  reason: string | null
  resolve_method: string | null
  maker: string | null
  propose_time: string | null
  resolve_time: string | null
  status: string | null
  type: string | null
  original_type: string | null
  sprint_id: string | null
  /** 由 rdm_sprint 反查,便于列表直接显示迭代名而不是裸 id */
  sprint_name: string | null
  project_id: string | null
  story_key: string | null
  verify_note: string | null
  is_repeated: string | null
  is_occasional: string | null
  last_editor: string | null
  last_edit_time: string | null
  bounce_count: number | null
  rdm_key: string | null
}

export interface DocBugListResponse {
  total: number
  page: number
  page_size: number
  items: DocBugRecord[]
}

/** 一条截图的元数据 —— 不含二进制,所以能和清单一起回来(实测整包 < 1KB) */
export interface DocBugImageMeta {
  id: number
  /** 同一故障内的序号,从 1 开始(先按来源列,再按表内行序) */
  seq: number
  /** 来源列:截图1 / 截图2 */
  column_label: string | null
  mime_type: string
  byte_size: number | null
  width: number | null
  height: number | null
  thumb_mime: string | null
  thumb_byte_size: number | null
}

export interface DocBugImageListResponse {
  key: string
  total: number
  items: DocBugImageMeta[]
}

/** 被跳过的行按原因分桶 —— 逐行回吐会把 400+ 行刷成一堵墙 */
export interface UploadSkipSummary {
  /** 表内【sprint】列为空:该表 480 行里目前只有 43 行标了迭代 */
  no_sprint: number
  /** 标了 sprint,但该迭代属于别的项目 */
  other_project: number
  /** 标了 sprint,但在 rdm_sprint 里匹配不到同名迭代(多半是拼写不一致) */
  unknown_sprint: number
  /** 属于本次项目、但不是本次所选迭代的行(2026-09-19 起导入按迭代收窄) */
  other_sprint: number
  /** 命中了本次项目与迭代,但字段没通过校验(详见 errors 的行号) */
  invalid: number
  /** 被删除线划掉的废弃行 */
  strikethrough: number
}

/**
 * 导入前校验的结果 —— 与上传响应刻意同形,前端复用同一套渲染。
 *
 * 与 UploadResponse 的区别只有一处:这里没有 images/imported,多了 header_ok /
 * importable / valid / invalid_detail。因为校验**不写任何表**,图片自然无从谈起。
 */
export interface ValidateResponse {
  success: boolean
  project_id: string
  /** 回显本次选中的迭代 —— 报告里的数字都只对这一个迭代成立 */
  sprint_id: string
  /** 表头是否齐备(缺「自动编号/问题详述/sprint」任一 ⇒ false,整份文件不可用) */
  header_ok: boolean
  /** 本次取值范围(有 sprint、属于所选项目、且就是所选迭代)内,能通过校验的行数 */
  importable: number
  /** 审完确实有可导入的行。为 false 时 errors 里会带上 sprint 层面的原因 */
  valid: boolean
  /** 读取到的数据行总数(≠ 校验范围内的行数) */
  total_count: number
  skipped: UploadSkipSummary
  /** 逐行问题清单(含 sheet 行号),上限 50 条 */
  errors: string[]
  /**
   * 按字段聚合的问题行数,如 `{ '故事号': 40 }`。
   * ⚠ 逐条清单会被 50 条上限截断,故「一共多少行同类问题」只能看这里。
   */
  invalid_detail: Record<string, number>
  /** 本次校验覆盖到的迭代 */
  sprints: { sprint_id: string; sprint_name: string | null; count: number }[]
  file_size: number
}

export interface UploadResponse {
  success: boolean
  imported?: number
  total_count?: number
  skipped?: UploadSkipSummary
  errors?: string[]
  sprints?: { sprint_id: string; sprint_name: string | null; count: number }[]
  project_id?: string
  /** 回显本次选中的迭代 */
  sprint_id?: string
  file_size?: number
  /** 随行入库的截图张数(源文件没有内嵌图片时为 0) */
  images?: number
  images_total_bytes?: number
  /** 截图环节耗时(秒)——297MB 文件导入的时间去向,便于判断性能回退 */
  image_seconds?: number
  /** 锚点统计:anchors_total / images_yielded / skipped_row_not_imported … */
  image_stats?: Record<string, number>
  /** 截图写入失败的原因。业务行已落库,不因此回滚 */
  image_error?: string | null
  /** 未改动图片表时的说明(源文件没有内嵌图片,已有截图被保留) */
  image_skipped?: string | null
}

// ── 文档测试用例导入 ────────────────────────────────────────────────
/**
 * 一行测试用例(rdm_testcase)。
 *
 * ⚠ 该表由「文档导入」通道唯一写入(RDM 侧的测试用例自动采集已下线),
 *   故列表里的行都来自文档导入(见后端 data_import.py 的「文档测试用例导入」小节)。
 */
export interface TestcaseRecord {
  case_key: string | null
  case_name: string | null
  /** Jira 侧用例状态(如「待办」)。源文档没有这一列,文档导入的行恒为 null */
  status: string | null
  /** 执行状态(customfield_11107),源文档的「最新结果」列 */
  exec_status: string | null
  /** 落库在 module 字段,值是「用例集」名(源文档的「测试用例集」列) */
  module: string | null
  /** 关联故事(源文档的「需求」列)。报表的「用例覆盖率」就靠它 */
  story_key: string | null
  labels: string | null
  sprint_id: string | null
  sprint_name: string | null
  project_id: string | null
  project_name: string | null
  updated: string | null
  /** steps JSON 里的步骤条数;steps 为空或不是合法 JSON 时为 0 */
  step_count: number
}

export interface TestcaseListResponse {
  total: number
  page: number
  page_size: number
  items: TestcaseRecord[]
}

/**
 * 一个故事号解析出来的迭代归属(后端 resolve_testcase_sprints 的产物)。
 *
 * ⚠ `state` 仅供参考展示:同一故事号在 rdm_issue 里可能跨迭代留行(同步是「按 sprint
 *   增量写 + 只清本迭代旧行」,故事挪迭代后旧行会留在原迭代),后端按
 *   active > future > closed、再取 sprint_id 最大者定一条,这里显示的就是被选中的那条。
 */
export interface TestcaseStoryResolved {
  story_key: string
  sprint_id: string | null
  sprint_name: string | null
  project_id: string | null
  project_name: string | null
  state: string | null
  /** 该故事号下有多少个用例 */
  case_count: number
}

/** 跳过原因分桶。字段名与后端 build_testcase_cases 的返回逐字对应 */
export interface TestcaseSkipSummary {
  /** 步骤行出现在任何用例之前,没有可挂靠的用例 */
  orphan_step: number
  /** 【关键字】为空且不是步骤行 —— 既不是用例也不是步骤 */
  no_case_key: number
  /** 【需求】为空:没有故事 key 就没法幂等(唯一键含 story_key),故整个用例跳过 */
  no_story: number
  /** 只有步骤ID、没有任何内容的空壳步骤行 */
  empty_step: number
}

/**
 * 校验与导入**同形**的报告 —— 后端 testcase_report() 一套输出,前端一套渲染。
 * 这是刻意的:`/testcases/validate` 与 `/testcases/upload` 走同一个
 * evaluate_testcase_import(),故「校验通过」与「导得进去」必然一致 —— 不存在文档故障
 * 那边的 strict/宽松双口径,界面也就不需要两套组件。
 */
export interface TestcaseReport {
  /** 导入接口=是否真写库了;校验接口=等价于 valid */
  success: boolean
  /** 整份文件可导入。false 时 errors 里是原因(故事号查不到 / 表头缺列 / 迭代跨项目) */
  valid: boolean
  project_id?: string
  /** 表头是否齐备(缺【关键字】/【需求】即 false) */
  header_ok: boolean
  /** 归并出的用例数 */
  case_count?: number
  /** 读到的数据行总数(源文档里一个用例占多行,故恒 ≥ 用例数) */
  total_rows?: number
  /** 折进 steps JSON 的步骤总数 */
  step_count?: number
  /** 待写入/已写入的**行数**(一个用例引多个故事时 > case_count) */
  importable?: number
  /** 仅导入接口:实际写入行数 */
  imported?: number
  skipped?: TestcaseSkipSummary
  case_sets?: { name: string; count: number }[]
  /** 本次覆盖的故事号 → 迭代归属(校验报告的核心内容) */
  stories?: TestcaseStoryResolved[]
  /** 在 rdm_issue 里查不到的故事号 —— 非空即整份拒绝 */
  missing_stories?: string[]
  errors?: string[]
  /** 实际用于解码的编码(utf-8-sig / utf-8 / gbk)—— 中文 CSV 最容易在这里出问题 */
  encoding?: string
  file_size?: number
}

export const dataImportApi = {
  /**
   * 某项目下 state='closed' 的迭代 —— 导入向导第 2 步「选择 Sprint」的数据源。
   * (同一个查询也带 rdm_sprint_exclude 屏蔽名单,即那份名单的展示入口 C。)
   *
   * ⚠ sprint_id 的类型是 **string**,不是 number:库里的 `rdm_sprint.sprint_id` 与
   *   `rdm_doc_bug.sprint_id` 都是 varchar(50),拿 number 接会在与文档解析出的
   *   sprint_id 做比较时静默不等 —— 而导入的收窄判定正是靠这个比较。
   */
  getClosedSprints(projectId: number): Promise<{ sprint_id: string; sprint_name: string }[]> {
    return get<{ sprint_id: string; sprint_name: string }[]>(`/data-import/sprints/${projectId}`)
  },

  /** 项目维度的文档故障列表;sprintId 传了才按迭代收窄 */
  getDocBugs(
    projectId: string,
    page: number,
    pageSize: number,
    sprintId?: string
  ): Promise<DocBugListResponse> {
    return get<DocBugListResponse>('/data-import/doc-bugs', {
      project_id: projectId,
      page,
      page_size: pageSize,
      ...(sprintId ? { sprint_id: sprintId } : {}),
    })
  },

  clearDocBugs(projectId: string, sprintId?: string): Promise<{ deleted: number }> {
    return del<{ deleted: number }>('/data-import/doc-bugs', {
      data: { project_id: projectId, ...(sprintId ? { sprint_id: sprintId } : {}) },
    })
  },

  /**
   * 上传整份「问题明细表」:每一行的迭代归属仍取自表内 sprint 列,但**只有与
   * sprintId 相同的那一个迭代**的行会被写入,其余行按原因跳过(见 UploadSkipSummary)。
   *
   * ⚠ sprintId 必传(不是可选):后端漏了它就会把整个项目的行都导进来,而界面上
   *   完全看不出来 —— 一份问题明细表含多个迭代,按迭代分次导入是现在的正常用法。
   */
  async uploadDocBugs(projectId: string, sprintId: string, file: File): Promise<UploadResponse> {
    const formData = new FormData()
    // 与磁盘解耦后再上传,见 detachedFile 的注释(防 ERR_UPLOAD_FILE_CHANGED)
    formData.append('file', await detachedFile(file))
    return post<UploadResponse>(
      `/data-import/doc-bugs/upload?project_id=${encodeURIComponent(projectId)}`
      + `&sprint_id=${encodeURIComponent(sprintId)}`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        // 全局 axios timeout 是 30s,而这份表内嵌 390 张截图、实测 297MB ——
        // 按 30s 掐断会在数据写库前就 abort,用户看到的是「导入失败」但其实文件没传完。
        timeout: 30 * 60 * 1000,
      }
    )
  },

  /**
   * 导入前校验:同一份文件、同一套判定,但**只读不写库**,可反复调用。
   *
   * 为什么要有这一步:上传接口的判定是宽容的 —— 不合格的行跳过、其余照常写入。
   * 用户拿到的是一个**已经落库的结果**,想改得先清空再重来。校验接口把同一套
   * 判定以更严的口径(strict)跑一遍,先出报告,用户确认后再决定导不导。
   *
   * 与 uploadDocBugs 同样放宽 timeout:这份表内嵌 390 张截图、实测 297MB,
   * 交给 30s 的全局超时会在读盘阶段就被 abort,而用户看到的是"校验失败"但其实
   * 文件都没传完。
   *
   * 取值范围与 uploadDocBugs 严格一致 —— 同样是「所选项目 ∩ 所选迭代」。
   * 两边范围若不同源,校验说"3 条可导入"而实际写入 42 条,报告就成了误导。
   */
  async validateDocBugs(
    projectId: string,
    sprintId: string,
    file: File
  ): Promise<ValidateResponse> {
    const formData = new FormData()
    // 与磁盘解耦后再上传,见 detachedFile 的注释(防 ERR_UPLOAD_FILE_CHANGED)
    formData.append('file', await detachedFile(file))
    return post<ValidateResponse>(
      `/data-import/doc-bugs/validate?project_id=${encodeURIComponent(projectId)}`
      + `&sprint_id=${encodeURIComponent(sprintId)}`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30 * 60 * 1000,
      }
    )
  },

  /** 单条文档故障的全部字段。故障明细列表只回吐列表需要的列,详情弹窗要全字段 */
  getDocBug(key: string): Promise<DocBugRecord> {
    return get<DocBugRecord>('/data-import/doc-bug', { key })
  },

  /** 某条文档故障的截图清单(只有元数据,不含二进制,响应极小) */
  getDocBugImages(key: string): Promise<DocBugImageListResponse> {
    return get<DocBugImageListResponse>('/data-import/doc-bug-images', { key })
  },

  // ── 文档测试用例导入 ──────────────────────────────────────────────
  /**
   * 导入前校验:同一份文件、同一套判定,但**只读不写库**,可反复调用。
   *
   * 为什么要有这一步:迭代归属现在**靠故事号反查 rdm_issue**,而故事号解析不到就整份
   * 拒绝 —— 这个判定必须在写库之前摊开给用户看。校验与上传走后端同一个
   * evaluate_testcase_import(),故报告结论就是导入的前置结论,不存在两套口径。
   */
  async validateTestcases(projectId: string, file: File): Promise<TestcaseReport> {
    const formData = new FormData()
    // 与磁盘解耦后再上传,见 detachedFile 的注释(防 ERR_UPLOAD_FILE_CHANGED)
    formData.append('file', await detachedFile(file))
    return post<TestcaseReport>(
      `/data-import/testcases/validate?project_id=${projectId}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
  },

  /**
   * 已入库的测试用例 —— 第 4 步「检查已有数据」的数据源。
   *
   * `storyKeys` 传文档里解析出的故事号,列表就只剩「这份文档会不会重复导入」相关的那批;
   * 不传则退化成该项目全量。去掉手选 Sprint 后,这是唯一还能界定「本次范围」的维度。
   */
  getTestcases(
    projectId: string,
    page: number,
    pageSize: number,
    storyKeys?: string[]
  ): Promise<TestcaseListResponse> {
    return get<TestcaseListResponse>(
      '/data-import/testcases',
      {
        project_id: projectId,
        page,
        page_size: pageSize,
        ...(storyKeys?.length ? { story_keys: storyKeys } : {}),
      },
      // ⚠ 必须显式指定:axios 1.x 默认把数组序列化成 `story_keys[]=K-1`,而 FastAPI 的
      //   list[str] Query 只认重复的 `story_keys=K-1` —— 带方括号的参数名对不上,后端会
      //   静默当成「没传」,筛选无声失效(拿到的还是全项目,肉眼看着也"正常")。
      //   实测(axios 1.20.0):default → `story_keys%5B%5D=K-1`;indexes:null → `story_keys=K-1`。
      { paramsSerializer: { indexes: null } }
    )
  },

  /**
   * 删除「本次文档涉及的故事号」下的测试用例。
   *
   * ⚠⚠ 删除**不区分来源**(rdm_testcase 未设来源列)—— 只要求例关联的故事号在这次
   *   文档里,表里对应的行都会被删。故 story_keys 必须由校验阶段解析出的
   *   故事号填充,后端也拒绝空数组(空范围 = 整个项目会被清空)。
   */
  clearTestcases(
    projectId: string,
    storyKeys: string[]
  ): Promise<{ deleted: number; story_count: number }> {
    return del<{ deleted: number; story_count: number }>('/data-import/testcases', {
      data: { project_id: projectId, story_keys: storyKeys },
    })
  },

  /**
   * 上传测试用例 CSV。迭代归属**由故事号反查**(不再传 sprint_id)——
   * 源文档里没有 sprint 列,但每行都有【需求】(故事号),而故事号经 rdm_issue
   * 能确定它现在所在的那个迭代。
   *
   * ⚠ 故事号解析不到 ⇒ 后端整份拒绝(success=false,一条都不写),报告形状与
   *   validateTestcases 完全一致,前端用同一套块渲染即可。
   */
  async uploadTestcases(projectId: string, file: File): Promise<TestcaseReport> {
    const formData = new FormData()
    // 与磁盘解耦后再上传,见 detachedFile 的注释(防 ERR_UPLOAD_FILE_CHANGED)
    formData.append('file', await detachedFile(file))
    return post<TestcaseReport>(
      `/data-import/testcases/upload?project_id=${projectId}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
  },
}

/**
 * 截图直链 —— 专供 `<img :src>` 使用。
 *
 * ⚠ 必须把 token 放进查询串:`<img>` 无法携带 Authorization 头;若改用 axios/fetch 取
 * 二进制再 `createObjectURL`,缓存就退化成内存缓存,刷新/重开即失效 —— 而浏览器对
 * `<img src>` 的原生缓存会复用后端的 ETag(内容 sha256),二次打开走 304、几乎零流量,
 * 这正是「打开详情不能慢」的实现基础。后端该接口因此只读、且只认这一个 query 参数。
 *
 * 路径前缀取 `import.meta.env.BASE_URL`:开发态是 `/`,生产态是 `/iterhub/`,
 * 与 axios 的 baseURL 同源,故 nginx 的 /iterhub/api 代理与 CSP 的 img-src 'self'
 * 都天然满足(不需为此新增任何 nginx 规则)。
 */
export function docBugImageUrl(imageId: number, thumb = false): string {
  const qs = new URLSearchParams()
  if (thumb) qs.set('thumb', '1')
  const token = localStorage.getItem('token')
  if (token) qs.set('t', token)
  const base = import.meta.env.BASE_URL || '/'
  return `${base}api/data-import/doc-bug-image/${imageId}?${qs.toString()}`
}
