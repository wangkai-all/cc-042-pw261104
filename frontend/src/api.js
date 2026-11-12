const BASE = '/api'

async function req(path, opts) {
  const r = await fetch(BASE + path, opts)
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail || detail } catch { /* ignore */ }
    throw new Error(detail)
  }
  return r.status === 204 ? null : r.json()
}

const json = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  repos: () => req('/repos'),
  register: (path, name) => req('/repos', json({ path, name: name || undefined })),
  unregister: (id) => req(`/repos/${id}`, { method: 'DELETE' }),
  collect: (id) => req(`/repos/${id}/collect`, { method: 'POST' }),
  overview: (id) => req(`/repos/${id}/overview`),
  commits: (id, batchId) => req(`/repos/${id}/commits${batchId ? `?batch_id=${batchId}` : ''}`),
  commit: (id, sha) => req(`/repos/${id}/commits/${sha}`),
  authors: (id, batchId, since, until) => {
    const q = new URLSearchParams()
    if (batchId) q.set('batch_id', batchId)
    if (since != null) q.set('since', since)
    if (until != null) q.set('until', until)
    const s = q.toString()
    return req(`/repos/${id}/authors${s ? `?${s}` : ''}`)
  },
  batches: (id) => req(`/repos/${id}/batches`),
  compare: (id, a, b) => req(`/repos/${id}/compare?a=${a}&b=${b}`),
}
