import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { fmtTime } from './util.js'

/** 作者统计：筛选用作者时间（提交自带时区显示）。 */
export default function AuthorsPanel({ repoId, batchId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')

  const load = useCallback(() => {
    const s = since ? Math.floor(new Date(since).getTime() / 1000) : null
    const u = until ? Math.floor(new Date(until).getTime() / 1000) : null
    api.authors(repoId, batchId, s, u).then(setData).catch((e) => setError(e.message))
  }, [repoId, batchId, since, until])

  useEffect(() => { load() }, [load])

  if (error) return <p className="error-banner">{error}</p>
  if (!data) return <p className="muted">加载中…</p>

  return (
    <div>
      <div className="filter-bar">
        <label>作者时间从 <input type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} /></label>
        <label>到 <input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
        {(since || until) && <button onClick={() => { setSince(''); setUntil('') }}>清除筛选</button>}
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>作者</th><th>邮箱</th><th>提交数</th><th>新增行</th><th>删除行</th>
            <th>文件数</th><th>二进制文件</th><th>首次提交</th><th>最近提交</th>
          </tr>
        </thead>
        <tbody>
          {data.authors.map((a) => (
            <tr key={a.author_email}>
              <td>{a.author_name}</td>
              <td className="mono">{a.author_email}</td>
              <td>{a.commits}</td>
              <td className="add">+{a.adds}</td>
              <td className="del">-{a.dels}</td>
              <td>{a.files}</td>
              <td>{a.binary_files}</td>
              <td>{fmtTime(a.first_commit, a.author_tz)}</td>
              <td>{fmtTime(a.last_commit, a.author_tz)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.authors.length === 0 && <p className="muted">该时间范围内没有提交。</p>}
    </div>
  )
}
