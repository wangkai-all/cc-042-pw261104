import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import CommitGraph from './CommitGraph.jsx'
import CommitDetail from './CommitDetail.jsx'
import AuthorsPanel from './AuthorsPanel.jsx'
import BranchesPanel from './BranchesPanel.jsx'
import BatchesPanel from './BatchesPanel.jsx'
import { fmtLocal } from './util.js'

const TABS = [
  ['graph', '提交图'],
  ['branches', '分支'],
  ['authors', '作者统计'],
  ['batches', '批次历史'],
]

export default function RepoDetail({ repoId, onBack, onError }) {
  const [overview, setOverview] = useState(null)
  const [batches, setBatches] = useState([])
  const [viewBatch, setViewBatch] = useState(null) // null = 当前(最新成功批次)
  const [tab, setTab] = useState('graph')
  const [selectedCommit, setSelectedCommit] = useState(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [ov, bs] = await Promise.all([api.overview(repoId), api.batches(repoId)])
      setOverview(ov)
      setBatches(bs)
    } catch (e) { onError(e.message) }
  }, [repoId, onError])

  useEffect(() => { refresh() }, [refresh])

  async function collect() {
    setBusy(true)
    try {
      await api.collect(repoId)
      setViewBatch(null)
      await refresh()
    } catch (e) { onError(e.message) } finally { setBusy(false) }
  }

  if (!overview) return <p className="muted">加载中…</p>
  const { repo, current_batch: current, running_batch: running } = overview
  const effectiveBatch = viewBatch ?? current?.id ?? null
  const viewingHistory = viewBatch != null && current && viewBatch !== current.id

  return (
    <div>
      <div className="detail-head">
        <button onClick={onBack}>← 返回</button>
        <h2>{repo.name}</h2>
        <span className="muted mono">{repo.path}</span>
        <button onClick={collect} disabled={busy}>
          {busy ? '采集中…' : running ? `续采中断的轮次 #${running.id}` : '采集一轮'}
        </button>
        <label>
          查看批次：
          <select
            value={effectiveBatch ?? ''}
            onChange={(e) => setViewBatch(Number(e.target.value))}
          >
            {batches.filter((b) => b.status === 'success').map((b) => (
              <option key={b.id} value={b.id}>
                #{b.id} · {fmtLocal(b.finished_at)}{current && b.id === current.id ? '（当前）' : ''}
              </option>
            ))}
          </select>
        </label>
      </div>
      {viewingHistory && (
        <div className="history-banner">
          正在查看历史批次 #{viewBatch} 的快照；页面的当前结果仍是批次 #{current.id}。
          <button onClick={() => setViewBatch(null)}>回到当前</button>
        </div>
      )}
      {!current && <p className="muted">尚未成功采集。点击「采集一轮」开始。</p>}
      {current && (
        <>
          <nav className="tabs">
            {TABS.map(([key, label]) => (
              <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </nav>
          {tab === 'graph' && (
            <div className="graph-layout">
              <CommitGraph repoId={repoId} batchId={effectiveBatch} onSelect={setSelectedCommit} selected={selectedCommit} />
              {selectedCommit && (
                <CommitDetail repoId={repoId} sha={selectedCommit} onClose={() => setSelectedCommit(null)} />
              )}
            </div>
          )}
          {tab === 'branches' && <BranchesPanel batches={batches} batchId={effectiveBatch} />}
          {tab === 'authors' && <AuthorsPanel repoId={repoId} batchId={effectiveBatch} />}
          {tab === 'batches' && (
            <BatchesPanel repoId={repoId} batches={batches} onView={(id) => { setViewBatch(id); setTab('graph') }} onError={onError} />
          )}
        </>
      )}
    </div>
  )
}
