import { useEffect, useState } from 'react'
import { api } from './api.js'
import { CHANGE_TYPE, fmtLocal, fmtTime, shortSha } from './util.js'

export default function CommitDetail({ repoId, sha, onClose }) {
  const [c, setC] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setC(null)
    api.commit(repoId, sha).then(setC).catch((e) => setError(e.message))
  }, [repoId, sha])

  if (error) return <aside className="commit-detail"><p className="error-banner">{error}</p></aside>
  if (!c) return <aside className="commit-detail"><p className="muted">加载中…</p></aside>

  return (
    <aside className="commit-detail">
      <div className="detail-title">
        <strong className="mono">{shortSha(c.sha)}</strong>
        <button onClick={onClose}>×</button>
      </div>
      <p className="commit-msg">{c.message}</p>
      <dl>
        <dt>作者</dt><dd>{c.author_name} &lt;{c.author_email}&gt;</dd>
        <dt>作者时间</dt><dd>{fmtTime(c.author_time, c.author_tz)}</dd>
        <dt>提交者</dt><dd>{c.committer_name} &lt;{c.committer_email}&gt;</dd>
        <dt>提交者时间</dt><dd>{fmtTime(c.committer_time, c.committer_tz)}</dd>
        <dt>采集时间</dt><dd>{fmtLocal(c.collected_at)}</dd>
        <dt>父提交</dt>
        <dd>{c.parents.length ? c.parents.map((p) => <span key={p} className="mono sha">{shortSha(p)}</span>) : '（根提交，相对空树计算）'}</dd>
      </dl>
      <h4>文件变更（{c.files.length}）</h4>
      <table className="files-table">
        <tbody>
          {c.files.map((f) => {
            const ct = CHANGE_TYPE[f.change_type] || { label: f.change_type, cls: '' }
            return (
              <tr key={`${f.old_path || ''}-${f.path}`}>
                <td><span className={`badge ${ct.cls}`}>{ct.label}</span></td>
                <td className="path-cell">
                  {f.old_path ? (
                    <span><span className="old-path">{f.old_path}</span> → <span className="new-path">{f.path}</span></span>
                  ) : (
                    <span>{f.path}</span>
                  )}
                </td>
                <td className="numstat">
                  {f.is_binary ? (
                    <span className="badge ct-bin">二进制</span>
                  ) : (
                    <><span className="add">+{f.additions}</span> <span className="del">-{f.deletions}</span></>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </aside>
  )
}
