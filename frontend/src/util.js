/** 时间格式化：按提交自带的时区偏移显示作者/提交者时间。 */

// tz 形如 "+0800" / "-0500"
export function tzOffsetMinutes(tz) {
  if (!tz || !/^[+-]\d{4}$/.test(tz)) return 0
  const sign = tz[0] === '+' ? 1 : -1
  return sign * (parseInt(tz.slice(1, 3), 10) * 60 + parseInt(tz.slice(3, 5), 10))
}

export function fmtTime(ts, tz) {
  if (ts == null) return '—'
  const offset = tzOffsetMinutes(tz)
  const d = new Date((ts + offset * 60) * 1000)
  const p = (n) => String(n).padStart(2, '0')
  const s = `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`
  return tz ? `${s} ${tz}` : s
}

export function fmtLocal(ts) {
  if (ts == null) return '—'
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function shortSha(sha) {
  return sha ? sha.slice(0, 8) : '—'
}

export const BRANCH_STATUS = {
  new: { label: '新分支', cls: 'st-new' },
  same: { label: '未变', cls: 'st-same' },
  forward: { label: '前进', cls: 'st-forward' },
  rewritten: { label: '改写', cls: 'st-rewritten' },
  deleted: { label: '已删除', cls: 'st-deleted' },
}

export const CHANGE_TYPE = {
  A: { label: '新增', cls: 'ct-a' },
  M: { label: '修改', cls: 'ct-m' },
  D: { label: '删除', cls: 'ct-d' },
  R: { label: '改名', cls: 'ct-r' },
}
