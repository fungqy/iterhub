// 「故障重开数」的档位边界 —— 卡片列与下钻弹窗筛选共用这一份定义。
//
// 为什么单独成文件:同一组边界有两个消费者 ——
//   ① ReopenDistributionCard 的三列(数值来自后端 /project-metrics 的分桶);
//   ② ReportReopenDialog 按列过滤(数值来自 /bugs/reopen 的 reopen_times)。
// 若两处各写一遍「≥3 算多次」,改边界时就会一边改一边漏,出现
// 「点『多次』那一格,弹窗却把某只 3 次的故障归到 2 次」这种自相矛盾。
// 边界只写在这里,卡片与弹窗都从这里取。
//
// ⚠ REOPEN_MANY_MIN 必须与后端 reports.py 里 reopen_many 的判定(times >= 3)保持一致。

export type ReopenBucket = 'all' | 'once' | 'twice' | 'many'

/** 「多次」档的下界。 */
export const REOPEN_MANY_MIN = 3

/** 档位顺序,与卡片列序一致(1 次 → 2 次 → 多次)。 */
export const REOPEN_BUCKETS: ReopenBucket[] = ['all', 'once', 'twice', 'many']

/**
 * 单只故障按重开次数归入某个非「全部」档位。
 * reopen_times ≤ 0 理论上不会出现(取得该行的 JOIN 已只保留重开记录),兜底归 'once' 无害。
 */
export function reopenBucketOf(times: number): Exclude<ReopenBucket, 'all'> {
  const n = Number(times) || 0
  if (n >= REOPEN_MANY_MIN) return 'many'
  if (n === 2) return 'twice'
  return 'once'
}

/** 给定次数是否落在档位内('all' 恒为真)。弹窗过滤的唯一判据。 */
export function matchesReopenBucket(times: number, bucket: ReopenBucket): boolean {
  return bucket === 'all' || reopenBucketOf(times) === bucket
}

/** 档位短标签(弹窗分段控件用)。卡片列头不取这里 —— 那是版式决定,只受宽度约束。 */
export function reopenBucketLabel(bucket: ReopenBucket): string {
  switch (bucket) {
    case 'once':
      return '重开 1 次'
    case 'twice':
      return '重开 2 次'
    case 'many':
      return `多次（≥${REOPEN_MANY_MIN} 次）`
    default:
      return '全部'
  }
}
