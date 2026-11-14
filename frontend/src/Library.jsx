import { useEffect, useMemo, useState } from 'react'
import { aclLabel, apiFetch, apiJson, documentTitle } from './api'
import { Icon, Spinner } from './ui'

const TIERS = [
  { id: 'public', label: 'Everyone' },
  { id: 'department', label: 'A department' },
  { id: 'team', label: 'A team' },
  { id: 'restricted', label: 'Named people' },
]

export function LibraryWorkspace({ isAdmin, access, reloadAccess, onNotice }) {
  const [filter, setFilter] = useState('')
  const [allDocs, setAllDocs] = useState(null)

  const loadAll = async () => {
    if (!isAdmin) return
    try { setAllDocs((await apiJson('/documents')).documents) } catch (error) { onNotice(error.message) }
  }
  useEffect(() => { loadAll() }, [isAdmin])

  const docs = isAdmin && allDocs ? allDocs : access.documents || []
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    return needle ? docs.filter((doc) => `${doc.filename} ${aclLabel(doc)}`.toLowerCase().includes(needle)) : docs
  }, [docs, filter])

  return (
    <section className="page" aria-label="Documents">
      <header className="page-head">
        <div>
          <p className="kicker">{isAdmin ? 'All documents' : 'Your library'}</p>
          <h1>Documents</h1>
          <p className="lede">{isAdmin
            ? `${docs.length} documents in the workspace. Each one is readable only by the people its access rule names.`
            : `The ${docs.length} documents your account can read. Meridian answers only from these.`}</p>
        </div>
        <button className="ghost-button" onClick={() => { reloadAccess(); loadAll() }}><Icon name="refresh" size={15} /> Refresh</button>
      </header>

      {isAdmin && <UploadPanel onUploaded={() => { reloadAccess(); loadAll() }} onNotice={onNotice} />}

      <div className="table-tools">
        <label className="search-field"><Icon name="search" size={16} />
          <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter by title or access" aria-label="Filter documents" />
        </label>
        <span className="muted">{shown.length} shown</span>
      </div>

      {shown.length === 0
        ? <div className="empty"><Icon name="file" size={26} /><p>{docs.length ? 'No documents match this filter.' : 'No documents are shared with your account yet.'}</p></div>
        : (
          <table className="doc-table">
            <thead><tr><th>Title</th><th>Readable by</th><th>Status</th><th><span className="sr-only">Download</span></th></tr></thead>
            <tbody>
              {shown.map((doc) => (
                <tr key={doc.id}>
                  <td><span className="doc-title">{documentTitle(doc)}</span><span className="mono muted">#{doc.id}</span></td>
                  <td><span className={'access-tag tier-' + doc.permission_tier}>{aclLabel(doc)}</span></td>
                  <td><span className={'status status-' + doc.status}>{doc.status}</span></td>
                  <td className="cell-action"><a className="icon-button" href={`/api/documents/${doc.id}/download`} aria-label={`Download ${documentTitle(doc)}`}><Icon name="download" size={16} /></a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </section>
  )
}

function UploadPanel({ onUploaded, onNotice }) {
  const [file, setFile] = useState(null)
  const [tier, setTier] = useState('department')
  const [departments, setDepartments] = useState([])
  const [teams, setTeams] = useState([])
  const [department, setDepartment] = useState('')
  const [team, setTeam] = useState('')
  const [people, setPeople] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([apiJson('/admin/departments'), apiJson('/admin/teams')])
      .then(([d, t]) => { setDepartments(d.departments.filter((x) => x.is_active)); setTeams(t.teams.filter((x) => x.is_active)) })
      .catch((error) => onNotice(error.message))
  }, [])

  const ready = file && (tier === 'public' || (tier === 'department' && department) || (tier === 'team' && team) || (tier === 'restricted' && people.trim()))

  const submit = async (event) => {
    event.preventDefault()
    if (!ready) return
    setBusy(true)
    const body = new FormData()
    body.append('file', file)
    body.append('permission_tier', tier)
    if (tier === 'department') body.append('permission_department', department)
    if (tier === 'team') body.append('permission_team', team)
    if (tier === 'restricted') body.append('restricted_user_ids', people)
    try {
      const response = await apiFetch('/documents/upload', { method: 'POST', body })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || 'Upload failed.')
      onNotice(`${data.filename} is processed and searchable.`)
      setFile(null)
      event.target.reset()
      onUploaded()
    } catch (error) { onNotice(error.message) } finally { setBusy(false) }
  }

  return (
    <form className="panel upload" onSubmit={submit}>
      <div className="panel-title"><h2>Add a document</h2><p className="muted">PDF up to 20 MB. Text is extracted, indexed and searchable as soon as processing finishes.</p></div>
      <label className={'drop' + (file ? ' has-file' : '')}>
        <Icon name="upload" size={20} />
        <span>{file ? file.name : 'Choose a PDF'}</span>
        <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] || null)} />
      </label>
      <fieldset className="tier-picker">
        <legend>Who can read it</legend>
        {TIERS.map((t) => (
          <label key={t.id} className={tier === t.id ? 'is-on' : ''}>
            <input type="radio" name="tier" value={t.id} checked={tier === t.id} onChange={() => setTier(t.id)} />{t.label}
          </label>
        ))}
      </fieldset>
      {tier === 'department' && <label className="field">Department<select value={department} onChange={(e) => setDepartment(e.target.value)} required><option value="">Choose…</option>{departments.map((d) => <option key={d.id}>{d.name}</option>)}</select></label>}
      {tier === 'team' && <label className="field">Team<select value={team} onChange={(e) => setTeam(e.target.value)} required><option value="">Choose…</option>{teams.map((t) => <option key={t.id} value={t.name}>{t.department} · {t.name}</option>)}</select></label>}
      {tier === 'restricted' && <label className="field">User IDs<input value={people} onChange={(e) => setPeople(e.target.value)} placeholder="USR-00007, USR-00012" required /></label>}
      <div className="panel-actions">
        <button className="primary-button" disabled={!ready || busy}>{busy ? <><Spinner /> Processing…</> : <>Upload and index</>}</button>
      </div>
    </form>
  )
}
