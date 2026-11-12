import { useState } from 'react'
import { api } from './api.js'
import { fmtLocal } from './util.js'

export default function RepoList({ repos, onOpen, onChanged, onError }) {
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function register(e) {
    e.preventDefault()
    if (!path.trim()) return
    setBusy(true)
    try {
      await api.register(path.trim(), name.trim())
      setPath(''); setName('')
      onChanged()
    } catch (e2) { onError(e2.message) } finally { setBusy(false) }
  }

  async function collect(id, ev) {
    ev.stopPropagation()
    setBusy(true)
    try {
      await api.collect(id)
      onChanged()
    } catch (e2) { onError(e2.message) } finally { setBusy(false) }
  }

  async function remove(id, ev) {
    ev.stopPropagation()
    if (!confirm('确定取消登记？已采集的统计数据将一并删除。')) return
    try { await api.unregister(id); onChanged() } catch (e2) { onError(e2.message) }
  }

  return (
    <div>
      <form className="register-form" onSubmit={register}>
        <input
          placeholder="本地仓库路径，如 /path/to/repo"
          value={path}
          onChange={(e) => setPath(e.target.value)}
        />
        <input
          className="name-input"
          placeholder="名称（可选）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" disabled={busy}>登记仓库</button>
      </form>
      {repos.length === 0 && <p className="muted">还没有登记的仓库。登记一个本地 Git 仓库路径开始统计。</p>}
      <div className="repo-cards">
        {repos.map((r) => (
          <div key={r.id} className="repo-card" onClick={() => onOpen(r.id)}>
            <div className="repo-card-head">
              <strong>{r.name}</strong>
              <span className="muted mono">{r.path}</span>
            </div>
            <div className="repo-card-body">
              {r.current_batch ? (
                <span>当前批次 #{r.current_batch.id} · 完成于 {fmtLocal(r.current_batch.finished_at)}</span>
              ) : (
                <span className="muted">尚未成功采集</span>
              )}
              {r.running_batch && <span className="badge st-running">有中断的轮次 #{r.running_batch.id}（采集将续跑）</span>}
            </div>
            <div className="repo-card-actions">
              <button disabled={busy} onClick={(e) => collect(r.id, e)}>采集一轮</button>
              <button className="danger" onClick={(e) => remove(r.id, e)}>取消登记</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
