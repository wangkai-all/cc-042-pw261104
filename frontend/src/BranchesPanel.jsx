import { BRANCH_STATUS, shortSha } from './util.js'

/** 分支面板：展示所查看批次的分支快照（含改写/删除记录）。 */
export default function BranchesPanel({ batches, batchId }) {
  const batch = batches.find((b) => b.id === batchId)
  if (!batch) return <p className="muted">没有分支数据。</p>

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>分支</th><th>状态</th><th>当前指向</th><th>上轮指向</th><th>可达提交数</th>
        </tr>
      </thead>
      <tbody>
        {batch.branches.map((b) => {
          const st = BRANCH_STATUS[b.status] || { label: b.status, cls: '' }
          return (
            <tr key={b.name} className={b.status === 'deleted' ? 'row-deleted' : ''}>
              <td><strong>{b.name}</strong></td>
              <td><span className={`badge ${st.cls}`}>{st.label}</span></td>
              <td className="mono">{shortSha(b.tip_sha)}</td>
              <td className="mono">{shortSha(b.prev_tip_sha)}</td>
              <td>{b.status === 'deleted' ? '—' : b.reachable_count}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
