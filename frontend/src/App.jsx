import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import RepoList from './RepoList.jsx'
import RepoDetail from './RepoDetail.jsx'

export default function App() {
  const [repos, setRepos] = useState([])
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      setRepos(await api.repos())
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <div className="app">
      <header className="app-header">
        <h1>本地 Git 仓库统计</h1>
        <span className="muted">分支改写可追踪 · 无需远程平台</span>
      </header>
      {error && <div className="error-banner" onClick={() => setError(null)}>{error}</div>}
      {selected == null ? (
        <RepoList repos={repos} onOpen={setSelected} onChanged={refresh} onError={setError} />
      ) : (
        <RepoDetail repoId={selected} onBack={() => { setSelected(null); refresh() }} onError={setError} />
      )}
    </div>
  )
}
