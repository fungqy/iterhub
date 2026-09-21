// PrimeVue 全局中文 locale。
//
// 起因(用户反馈):下拉框选项为空时,PrimeVue 直接渲染内置的英文文案
// 「No available options」。这个串不是我们写的,而是 @primevue/core/config 的
// defaultOptions.locale.emptyMessage,只有显式配置 locale 才会被替换。
//
// 此前的处理方式是「哪个下拉框露英文就在哪个组件挂 #empty 插槽」,
// 只补了 ManualExecuteDialog 的 MultiSelect 一处(它还要区分「加载中」与「确实无数据」)。
// 但 Select / MultiSelect / DatePicker / 筛选菜单 / 分页器…凡是消费 locale 文案的地方
// 都还有英文,逐个补插槽既漏又多。这里改为一处统领:
// main.ts 的 app.use(PrimeVue, { locale }) 全局注入,所有组件同时生效。
// ⚠ 组件本地仍可用 #empty / #emptyfilter 等插槽覆盖本表(插槽优先级更高),
//    ManualExecuteDialog 的「正在加载迭代列表…」就是这种特例,两者不冲突。
//
// 为什么是「整份 locale 而不是只写 emptyMessage」:
// PrimeVue 安装时用 mergeKeys(defaultOptions, options) 合并 —— 该合并的深度
// 不由我们控制,一旦 locale 是整体替换而非逐键合并,只给一个 emptyMessage
// 会把 dayNames / monthNames 等一起抹成 undefined,DatePicker(ExecutionLogTable 在用)
// 会直接空白。因此这里给出完整字段,两种合并语义下结果都一致。
//
// 取值口径:沿用 PrimeVue 官方 zh 语言包的习惯译法,并统一成项目内的措辞习惯
// (「暂无可选项」对齐已有的「暂无可选迭代」)。改动文案只改本文件。
//
// ⚠ 类型来自 primevue/config 的 PrimeVueConfiguration['locale'],
//   而不是 @primevue/core/config 的 PrimeVueLocaleOptions —— 后者是 pnpm 下的
//   间接依赖,没有提升到 frontend/node_modules,直接 import 会解析失败。
import type { PrimeVueConfiguration } from 'primevue/config'

type PrimeVueLocale = NonNullable<PrimeVueConfiguration['locale']>

export const primevueLocale: PrimeVueLocale = {
  startsWith: '以…开始',
  contains: '包含',
  notContains: '不包含',
  endsWith: '以…结束',
  equals: '等于',
  notEquals: '不等于',
  noFilter: '无筛选',
  lt: '小于',
  lte: '小于或等于',
  gt: '大于',
  gte: '大于或等于',
  dateIs: '日期为',
  dateIsNot: '日期不为',
  dateBefore: '日期早于',
  dateAfter: '日期晚于',
  clear: '清除',
  apply: '应用',
  matchAll: '全部匹配',
  matchAny: '任意匹配',
  addRule: '添加规则',
  removeRule: '删除规则',
  accept: '是',
  reject: '否',
  choose: '选择',
  upload: '上传',
  cancel: '取消',
  completed: '已完成',
  pending: '待处理',
  fileSizeTypes: ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'],
  dayNames: ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'],
  dayNamesShort: ['周日', '周一', '周二', '周三', '周四', '周五', '周六'],
  dayNamesMin: ['日', '一', '二', '三', '四', '五', '六'],
  monthNames: [
    '一月',
    '二月',
    '三月',
    '四月',
    '五月',
    '六月',
    '七月',
    '八月',
    '九月',
    '十月',
    '十一月',
    '十二月',
  ],
  monthNamesShort: [
    '1月',
    '2月',
    '3月',
    '4月',
    '5月',
    '6月',
    '7月',
    '8月',
    '9月',
    '10月',
    '11月',
    '12月',
  ],
  chooseYear: '选择年份',
  chooseMonth: '选择月份',
  chooseDate: '选择日期',
  prevDecade: '上一个十年',
  nextDecade: '下一个十年',
  prevYear: '上一年',
  nextYear: '下一年',
  prevMonth: '上个月',
  nextMonth: '下个月',
  prevHour: '上一小时',
  nextHour: '下一小时',
  prevMinute: '上一分钟',
  nextMinute: '下一分钟',
  prevSecond: '上一秒',
  nextSecond: '下一秒',
  am: '上午',
  pm: '下午',
  today: '今天',
  weekHeader: '周',
  // 中文习惯以周一为一周首日(Aura 默认是 0=周日)。
  firstDayOfWeek: 1,
  showMonthAfterYear: false,
  dateFormat: 'yy-mm-dd',
  weak: '弱',
  medium: '中',
  strong: '强',
  passwordPrompt: '请输入密码',
  // ── 空态文案(本次反馈的落点)──
  // emptyMessage:下拉框无选项;emptyFilterMessage:筛选后无匹配;
  // emptySelectionMessage / selectionMessage:多选类的已选提示;searchMessage:筛选结果数。
  emptyMessage: '暂无可选项',
  emptyFilterMessage: '未找到匹配结果',
  emptySearchMessage: '未找到匹配结果',
  emptySelectionMessage: '未选择任何项',
  selectionMessage: '已选择 {0} 项',
  searchMessage: '找到 {0} 个结果',
  fileChosenMessage: '已选择 {0} 个文件',
  noFileChosenMessage: '未选择文件',
  // aria 文案同样走 locale:屏幕阅读器读到的按钮名也随之中文化。
  aria: {
    trueLabel: '是',
    falseLabel: '否',
    nullLabel: '未选择',
    star: '1 颗星',
    stars: '{star} 颗星',
    selectAll: '全选',
    unselectAll: '取消全选',
    close: '关闭',
    previous: '上一个',
    next: '下一个',
    navigation: '导航',
    scrollTop: '回到顶部',
    moveUp: '上移',
    moveTop: '移到顶部',
    moveDown: '下移',
    moveBottom: '移到底部',
    moveToTarget: '移到目标',
    moveToSource: '移回来源',
    moveAllToTarget: '全部移到目标',
    moveAllToSource: '全部移回来源',
    pageLabel: '第 {page} 页',
    firstPageLabel: '第一页',
    lastPageLabel: '最后一页',
    nextPageLabel: '下一页',
    prevPageLabel: '上一页',
    rowsPerPageLabel: '每页行数',
    jumpToPageDropdownLabel: '跳转到页码',
    jumpToPageInputLabel: '跳转到页码',
    selectRow: '选中行',
    unselectRow: '取消选中行',
    expandRow: '展开行',
    collapseRow: '收起行',
    showFilterMenu: '显示筛选菜单',
    hideFilterMenu: '隐藏筛选菜单',
    filterOperator: '筛选运算符',
    filterConstraint: '筛选条件',
    editRow: '编辑行',
    saveEdit: '保存编辑',
    cancelEdit: '取消编辑',
    listView: '列表视图',
    gridView: '网格视图',
    slide: '幻灯片',
    slideNumber: '{slideNumber}',
    zoomImage: '放大图片',
    zoomIn: '放大',
    zoomOut: '缩小',
    rotateRight: '向右旋转',
    rotateLeft: '向左旋转',
  },
}
