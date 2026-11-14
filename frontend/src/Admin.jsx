import { Fragment, useEffect, useState } from 'react'
import { apiJson } from './api'
import { Icon, Spinner } from './ui'

const ROLES = ['MEMBER', 'ADMIN', 'SUPER_ADMIN']

export function AdminWorkspace({ user, onNotice }) {
  const [users, setUsers] = useState([])
  const [departments, setDepartments] = useState([])
  const [teams, setTeams] = useState([])
  const [logs, setLogs] = useState([])
  const [editing, setEditing] = useState(null)
  const [secret, setSecret] = useState(null)

  const load = async () => {
    try {
      const [u, d, t, l] = await Promise.all([apiJson('/admin/users'), apiJson('/admin/departments'), apiJson('/admin/teams'), apiJson('/admin/audit-logs')])
      setUsers(u.users || []); setDepartments(d.departments || []); setTeams(t.teams || []); setLogs(l.logs || [])
    } catch (error) { onNotice(error.message) }
  }
  useEffect(() => { load() }, [])

  const act = async (fn, message) => {
    try { const result = await fn(); if (message) onNotice(typeof message === 'function' ? message(result) : message); await load(); return result } catch (error) { onNotice(error.message) }
  }

  return (
    <section className="page" aria-label="Administration">
      <header className="page-head">
        <div>
          <p className="kicker">Administration</p>
          <h1>People and access</h1>
          <p className="lede">Who can sign in, and which departments and teams they belong to. Document access follows these memberships.</p>
        </div>
        <button className="ghost-button" onClick={load}><Icon name="refresh" size={15} /> Refresh</button>
      </header>

      {secret && (
        <div className="secret" role="status">
          <div><strong>Temporary password for {secret.who}</strong><p className="muted">Shown once. Share it privately; they must change it at first sign-in.</p></div>
          <code>{secret.password}</code>
          <button className="icon-button" onClick={() => setSecret(null)} aria-label="Dismiss"><Icon name="close" size={16} /></button>
        </div>
      )}

      <div className="admin-top">
        <CreateMember onCreate={(form) => act(() => apiJson('/admin/users', { method: 'POST', body: { ...form, roles: ['MEMBER'] } }), (data) => { setSecret({ who: data.user.name, password: data.temporary_password }); return `Created ${data.user.id}.` })} />
        <dl className="stats">
          <div><dt>People</dt><dd>{users.length}</dd></div>
          <div><dt>Active</dt><dd>{users.filter((u) => u.is_active).length}</dd></div>
          <div><dt>Departments</dt><dd>{departments.filter((d) => d.is_active).length}</dd></div>
          <div><dt>Teams</dt><dd>{teams.filter((t) => t.is_active).length}</dd></div>
        </dl>
      </div>

      <section className="panel">
        <div className="panel-title"><h2>People</h2></div>
        <table className="doc-table people">
          <thead><tr><th>Name</th><th>Role</th><th>Memberships</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {users.map((item) => (
              <Fragment key={item.id}>
                <tr className={editing === item.id ? 'is-editing' : ''}>
                  <td><span className="doc-title">{item.name}</span><span className="mono muted">{item.id} · {item.email}</span></td>
                  <td>{item.roles.join(', ')}</td>
                  <td className="muted">{[...item.departments.map((d) => d.name), ...item.teams.map((t) => t.name)].join(', ') || '—'}</td>
                  <td><span className={'status ' + (item.is_active ? 'status-processed' : 'status-failed')}>{item.is_active ? 'active' : 'inactive'}</span></td>
                  <td className="cell-action row-actions">
                    <button className="ghost-button small" onClick={() => setEditing(editing === item.id ? null : item.id)}><Icon name="edit" size={14} /> Access</button>
                    <button className="ghost-button small" onClick={() => act(() => apiJson(`/admin/users/${item.id}/reset-password`, { method: 'POST', body: {} }), (data) => { setSecret({ who: item.name, password: data.temporary_password }); return null })}>Reset password</button>
                    {item.id !== user.user_id && <button className="ghost-button small" onClick={() => act(() => apiJson(`/admin/users/${item.id}`, { method: 'PATCH', body: { is_active: !item.is_active } }), `${item.name} ${item.is_active ? 'deactivated' : 'reactivated'}.`)}>{item.is_active ? 'Deactivate' : 'Reactivate'}</button>}
                  </td>
                </tr>
                {editing === item.id && (
                  <tr className="editor-row"><td colSpan={5}>
                    <AccessEditor person={item} departments={departments} teams={teams} onCancel={() => setEditing(null)}
                      onSave={async (roles, departmentIds, teamIds) => {
                        const ok = await act(async () => {
                          await apiJson(`/admin/users/${item.id}/roles`, { method: 'PUT', body: { roles } })
                          await apiJson(`/admin/users/${item.id}/memberships`, { method: 'PUT', body: { department_ids: departmentIds, team_ids: teamIds } })
                          return true
                        }, `Updated access for ${item.name}.`)
                        if (ok) setEditing(null)
                      }} />
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>

      <div className="admin-org">
        <OrgList title="Departments" items={departments} placeholder="New department name"
          onAdd={(name) => act(() => apiJson('/admin/departments', { method: 'POST', body: { name } }), 'Department created.')}
          onToggle={(item) => act(() => apiJson(`/admin/departments/${item.id}`, { method: 'PATCH', body: { is_active: !item.is_active } }), `${item.name} ${item.is_active ? 'archived' : 'reactivated'}.`)} />
        <OrgList title="Teams" items={teams} placeholder="New team name" departments={departments.filter((d) => d.is_active)}
          onAdd={(name, departmentId) => act(() => apiJson('/admin/teams', { method: 'POST', body: { name, department_id: Number(departmentId) } }), 'Team created.')}
          onToggle={(item) => act(() => apiJson(`/admin/teams/${item.id}`, { method: 'PATCH', body: { is_active: !item.is_active } }), `${item.name} ${item.is_active ? 'archived' : 'reactivated'}.`)} />
      </div>

      <section className="panel">
        <div className="panel-title"><h2>Recent activity</h2><p className="muted">Administrative actions. Credentials and session data are never logged.</p></div>
        <ol className="audit">
          {logs.slice(0, 20).map((log) => (
            <li key={log.id}><span className="mono">{log.created_at ? new Date(log.created_at).toLocaleString() : ''}</span><strong>{log.action.replace(/_/g, ' ')}</strong><span className="muted">{log.target_type} {log.target_id} · by {log.actor_user_id}</span></li>
          ))}
          {logs.length === 0 && <li className="muted">No administrative activity yet.</li>}
        </ol>
      </section>
    </section>
  )
}

function CreateMember({ onCreate }) {
  const [form, setForm] = useState({ name: '', email: '' })
  const [busy, setBusy] = useState(false)
  return (
    <form className="panel create" onSubmit={async (event) => { event.preventDefault(); setBusy(true); const ok = await onCreate(form); if (ok) setForm({ name: '', email: '' }); setBusy(false) }}>
      <div className="panel-title"><h2>Add a person</h2><p className="muted">They get a one-time password and choose their own at first sign-in.</p></div>
      <div className="field-row">
        <label className="field">Full name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
        <label className="field">Work email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></label>
        <button className="primary-button" disabled={busy}>{busy ? <Spinner /> : 'Add person'}</button>
      </div>
    </form>
  )
}

function AccessEditor({ person, departments, teams, onSave, onCancel }) {
  const [roles, setRoles] = useState(new Set(person.roles))
  const [deptIds, setDeptIds] = useState(new Set(person.departments.map((d) => d.id)))
  const [teamIds, setTeamIds] = useState(new Set(person.teams.map((t) => t.id)))
  const [busy, setBusy] = useState(false)
  const toggle = (set, setter, value) => { const next = new Set(set); next.has(value) ? next.delete(value) : next.add(value); setter(next) }
  return (
    <div className="access-editor">
      <fieldset><legend>Platform role</legend>
        {ROLES.map((role) => <label key={role} className="check"><input type="checkbox" checked={roles.has(role)} onChange={() => toggle(roles, setRoles, role)} />{role.replace('_', ' ').toLowerCase()}</label>)}
        <p className="muted small">Admin roles manage people; they do not grant access to document content.</p>
      </fieldset>
      <fieldset><legend>Departments</legend>
        {departments.filter((d) => d.is_active).map((d) => <label key={d.id} className="check"><input type="checkbox" checked={deptIds.has(d.id)} onChange={() => toggle(deptIds, setDeptIds, d.id)} />{d.name}</label>)}
      </fieldset>
      <fieldset className="wide"><legend>Teams</legend>
        <div className="check-grid">
          {teams.filter((t) => t.is_active).map((t) => <label key={t.id} className="check"><input type="checkbox" checked={teamIds.has(t.id)} onChange={() => toggle(teamIds, setTeamIds, t.id)} />{t.name}<span className="muted"> · {t.department}</span></label>)}
        </div>
      </fieldset>
      <div className="panel-actions">
        <button className="ghost-button" onClick={onCancel} type="button">Cancel</button>
        <button className="primary-button" type="button" disabled={busy || roles.size === 0} onClick={async () => { setBusy(true); await onSave([...roles], [...deptIds], [...teamIds]); setBusy(false) }}>{busy ? <Spinner /> : 'Save access'}</button>
      </div>
    </div>
  )
}

function OrgList({ title, items, placeholder, departments, onAdd, onToggle }) {
  const [name, setName] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  return (
    <section className="panel">
      <div className="panel-title"><h2>{title}</h2></div>
      <form className="inline-form" onSubmit={async (event) => { event.preventDefault(); await onAdd(name.trim(), departmentId); setName('') }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={placeholder} aria-label={placeholder} required />
        {departments && <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} required aria-label="Department"><option value="">Department…</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>}
        <button className="primary-button">Add</button>
      </form>
      <ul className="org-list">
        {items.map((item) => (
          <li key={item.id} className={item.is_active ? '' : 'is-archived'}>
            <span>{item.name}{item.department && <span className="muted"> · {item.department}</span>}</span>
            <button className="ghost-button small" onClick={() => onToggle(item)}>{item.is_active ? 'Archive' : 'Restore'}</button>
          </li>
        ))}
      </ul>
    </section>
  )
}
