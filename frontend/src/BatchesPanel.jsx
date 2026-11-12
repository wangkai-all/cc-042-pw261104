import { useState } from 'react'
import { api } from './api.js'
import { BRANCH_STATUS, fmtLocal, fmtTime, shortSha } from './util.js'

const BATCH_STATUS = {
  success: { label: '成功', cls: 'st-forward' },
  failed: { label: '失败', cls: 'st-deleted' },
  running: { label: '中断/进行中', cls: 'st-running' },
}

export default function BatchesPanel({ repoId, batches, onView, onError }) {
  const [picked, setPicked] = useState([])
  const [cmp, setCmp] = useState(null)

  function toggle(id) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)))
  }

  async function compare() {
    if (picked.length !== 2) return
    try {
      const [a, b] = [...picked].sort((x, y) => x - y)
      setCmp(await api.compare(repoId, a, b))
    } catch (e) { onError(e.message) }
  }

  return (
    <div>
      <div className="filter-bar">
        <span className="muted">勾选两个批次进行比较</span>
        <button disabled={picked.length !== 2} onClick={compare}>比较所选批次</button>
        {cmp && <button onClick={() => setCmp(null)}>关闭比较</button>}
      </div>

      {cmp && <CompareView cmp={cmp} />}

      <table className="data-table">
        <thead>
          <tr>
            <th></th><th>批次</th><th>状态</th><th>开始</th><th>结束</th>
            <th>提交数</th><th>分支快照</th><th>错误</th><th></th>
          </tr>
        </thead>
        <tbody>
          {batches.map((b) => {
            const st = BATCH_STATUS[b.status] || { label: b.status, cls: '' }
            return (
              <tr key={b.id}>
                <td>
                  {b.status === 'success' && (
                    <input type="checkbox" checked={picked.includes(b.id)} onChange={() => toggle(b.id)} />
                  )}
                </td>
                <td>#{b.id}</td>
                <td><span className={`badge ${st.cls}`}>{st.label}</span></td>
                <td>{fmtLocal(b.started_at)}</td>
                <td>{fmtLocal(b.finished_at)}</td>
                <td>{b.commit_count}</td>
                <td className="branch-chips">
                  {b.branches.map((br) => {
                    const bs = BRANCH_STATUS[br.status] || { label: br.status, cls: '' }
                    return (
                      <span key={br.name} className={`badge ${bs.cls}`} title={`${br.name}: ${bs.label}`}>
                        {br.name}·{bs.label}
                      </span>
                    )
                  })}
                </td>
                <td className="error-cell">{b.error || ''}</td>
                <td>
                  {b.status === 'success' && <button onClick={() => onView(b.id)}>查看快照</button>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function CompareView({ cmp }) {
  return (
    <div className="compare-view">
      {cmp.rewrites.length > 0 && (
        <section>
          <h4>分支改写记录</h4>
          <ul>
            {cmp.rewrites.map((r, i) => (
              <li key={i}>
                批次 #{r.batch}：分支 <strong>{r.name}</strong> 从 <span className="mono">{shortSha(r.from)}</span> 改写为 <span className="mono">{shortSha(r.to)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h4>分支指向变化</h4>
        {cmp.branch_changes.length === 0 ? <p className="muted">无变化</p> : (
          <ul>
            {cmp.branch_changes.map((c) => (
              <li key={c.name}>
                <strong>{c.name}</strong>：<span className="mono">{shortSha(c.a_tip)}</span> → <span className="mono">{shortSha(c.b_tip)}</span>
                {c.b_status && <span className={`badge ${(BRANCH_STATUS[c.b_status] || {}).cls || ''}`}>{(BRANCH_STATUS[c.b_status] || {}).label || c.b_status}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="compare-cols">
        <section>
          <h4>新增提交（{cmp.added.length}）</h4>
          <CommitList commits={cmp.added} />
        </section>
        <section>
          <h4>移除提交（{cmp.removed.length}）</h4>
          <CommitList commits={cmp.removed} />
        </section>
      </div>
    </div>
  )
}

function CommitList({ commits }) {
  if (commits.length === 0) return <p className="muted">无</p>
  return (
    <ul className="cmp-commits">
      {commits.map((c) => (
        <li key={c.sha}>
          <span className="mono sha">{shortSha(c.sha)}</span> {c.message.split('\n')[0]}
          <span className="muted"> · {c.author_name} · {fmtTime(c.author_time, c.author_tz)}</span>
        </li>
      ))}
    </ul>
  )
}
