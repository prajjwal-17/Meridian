import { StrictMode, useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { API_BASE, apiFetch, apiJson } from './api'
import { AdminWorkspace } from './Admin'
import { ChatWorkspace } from './Chat'
import { GraphWorkspace } from './Graph'
import { LibraryWorkspace } from './Library'
import { ChangePassword, Login, ThemeToggle } from './Login'
import { BrandMark, Icon } from './ui'

function initialDark() {
  try {
    const saved = localStorage.getItem('meridian-theme')
    if (saved) return saved === 'dark'
  } catch { /* storage unavailable */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

function App() {
  const [dark, setDark] = useState(initialDark)
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [view, setView] = useState('ask')
  const [health, setHealth] = useState('checking')
  const [notice, setNotice] = useState('')
  const [access, setAccess] = useState({ documents: null })
  const [chatKey, setChatKey] = useState(0)

  const isAdmin = user?.roles?.some((role) => ['ADMIN', 'SUPER_ADMIN'].includes(role.toUpperCase()))

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    try { localStorage.setItem('meridian-theme', dark ? 'dark' : 'light') } catch { /* ignore */ }
  }, [dark])

  const notify = useCallback((message) => { if (message) setNotice(message) }, [])

  const loadAccess = useCallback(async () => {
    try { setAccess({ documents: (await apiJson('/documents/accessible')).documents }) } catch (error) { setAccess({ documents: [] }); notify(error.message) }
  }, [notify])

  useEffect(() => {
    fetch(API_BASE + '/health').then((r) => setHealth(r.ok ? 'online' : 'offline')).catch(() => setHealth('offline'))
    apiFetch('/auth/me')
      .then(async (response) => { if (response.ok) setUser(await response.json()) })
      .finally(() => setAuthLoading(false))
  }, [])

  useEffect(() => { if (user && !user.must_change_password) loadAccess() }, [user?.user_id, user?.must_change_password])
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 6000); return () => clearTimeout(timer) }, [notice])

  const login = async (identifier, password) => {
    await apiJson('/auth/login', { method: 'POST', body: { identifier, password } })
    setUser(await apiJson('/auth/me'))
  }
  const changePassword = async (currentPassword, newPassword) => {
    await apiJson('/auth/change-password', { method: 'POST', body: { current_password: currentPassword, new_password: newPassword } })
    setUser(await apiJson('/auth/me'))
  }
  const logout = async () => {
    await apiFetch('/auth/logout', { method: 'POST' }).catch(() => null)
    setUser(null); setAccess({ documents: null }); setView('ask')
  }

  if (authLoading) return <div className="boot"><BrandMark size={34} /></div>
  if (!user) return <Login onLogin={login} dark={dark} setDark={setDark} />
  if (user.must_change_password) return <ChangePassword onChange={changePassword} onLogout={logout} user={user} dark={dark} setDark={setDark} />

  const nav = [
    { id: 'ask', label: 'Ask', icon: 'chat' },
    { id: 'library', label: 'Documents', icon: 'file', count: access.documents?.length },
    { id: 'graph', label: 'Entity graph', icon: 'graph' },
    ...(isAdmin ? [{ id: 'admin', label: 'People & access', icon: 'users' }] : []),
  ]
  const initials = user.name.split(' ').map((part) => part[0]).slice(0, 2).join('')

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Navigation">
        <button className="brand" onClick={() => { setView('ask'); setChatKey((k) => k + 1) }} aria-label="Meridian home, new question">
          <BrandMark size={26} /><span>Meridian</span>
        </button>
        <nav>
          {nav.map((item) => (
            <button key={item.id} className={'nav-item' + (view === item.id ? ' is-current' : '')} aria-current={view === item.id ? 'page' : undefined} onClick={() => setView(item.id)}>
              <Icon name={item.icon} size={18} /><span>{item.label}</span>{item.count !== undefined && <small>{item.count}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="me">
            <span className="avatar" aria-hidden="true">{initials}</span>
            <div><strong>{user.name}</strong><span className="muted">{(user.roles || []).map((r) => r.toLowerCase().replace('_', ' ')).join(', ')}</span></div>
          </div>
          <div className="foot-row">
            <span className={'health health-' + health} title={`API ${health}`}><i />{health === 'online' ? 'Connected' : health === 'offline' ? 'API offline' : 'Checking…'}</span>
            <ThemeToggle dark={dark} setDark={setDark} />
            <button className="icon-button" onClick={logout} aria-label="Sign out" title="Sign out"><Icon name="logout" size={17} /></button>
          </div>
        </div>
      </aside>
      <main className="main">
        {notice && (
          <div className="toast" role="status"><span>{notice}</span><button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss"><Icon name="close" size={15} /></button></div>
        )}
        {view === 'ask' && <ChatWorkspace key={chatKey} user={user} access={access} onNotice={notify} />}
        {view === 'library' && <LibraryWorkspace isAdmin={isAdmin} access={access} reloadAccess={loadAccess} onNotice={notify} />}
        {view === 'graph' && <GraphWorkspace onAsk={(prompt) => { setView('ask'); setChatKey((k) => k + 1); setTimeout(() => window.dispatchEvent(new CustomEvent('meridian:ask', { detail: prompt })), 0) }} />}
        {view === 'admin' && isAdmin && <AdminWorkspace user={user} onNotice={notify} />}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
