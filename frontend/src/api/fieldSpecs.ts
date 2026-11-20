/**
 * 图表与看板共用的列字段描述。
 *
 * 后端对应 backend/app/field_specs.py；这里只放前端列表、导出按钮和字段字典
 * 需要展示的列名与顺序，避免图表页和看板页各抄一份。
 */

export const CHART_COLUMNS = [
  '图表编号',
  '图表名称',
  '图表类型',
  '数据来源',
  '坐标字段',
  '聚合方式',
  '颜色方案',
  '图表状态',
] as const

export const DASHBOARD_COLUMNS = [
  '看板编号',
  '看板名称',
  '包含图表',
  '数据刷新',
  '可见范围',
  '创建人',
  '创建时间',
  '看板状态',
] as const

/** 图表消费字段字典的展示列，顺序与后端 /api/chart/fields 的条目一致。 */
export const CHART_FIELD_COLUMNS = [
  '来源',
  '字段名',
  '别名',
  '类型',
  '可聚合',
  '可求和',
  '图表编号',
  '图表名称',
] as const

export type ChartFieldColumn = (typeof CHART_FIELD_COLUMNS)[number]

/** 把字典条目里的布尔/数组值转成表格可读文本。 */
export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
