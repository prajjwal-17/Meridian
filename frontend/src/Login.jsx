import { useEffect, useState } from 'react'
import { apiFetch } from './api'
import { BrandMark, Icon, Spinner } from './ui'

function ThemeToggle({ dark, setDark }) {
  return (
    <button className="icon-button" onClick={() => setDark((value) => !value)} aria-label={dark ? 'Use light theme' : 'Use dark theme'} title={dark ? 'Light theme' : 'Dark theme'}>
      <Icon name={dark ? 'sun' : 'moon'} size={17} />
    </button>
  )
}

export function Login({ onLogin, dark, setDark }) {
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [demoAccounts, setDemoAccounts] = useState([])

  useEffect(() => {
    apiFetch('/auth/demo-accounts').then(async (response) => { if (response.ok) setDemoAccounts((await response.json()).accounts || []) }).catch(() => null)
  }, [])

  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('')
    try { await onLogin(identifier, password) } catch (failure) { setError(failure.message) } finally { setBusy(false) }
  }

  return (
    <div className="auth">
      <div className="auth-sheet">
        <header className="auth-brand"><BrandMark size={30} /><span>Meridian</span><ThemeToggle dark={dark} setDark={setDark} /></header>
        <h1>Sign in to your company’s documents</h1>
        <p className="lede">Ask questions in plain language. Every answer cites the page it came from, and you only ever see documents shared with you.</p>
        <form onSubmit={submit} className="auth-form">
          <label className="field">Email or user ID<input value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoComplete="username" required autoFocus /></label>
          <label className="field">Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button wide" disabled={busy}>{busy ? <><Spinner /> Signing in…</> : 'Sign in'}</button>
        </form>
      </div>
      {demoAccounts.length > 0 && (
        <aside className="auth-demo" aria-label="Demo accounts">
          <p className="kicker">Development only</p>
          <h2>Demo accounts</h2>
          <p className="muted">Fictional employees with different departments and teams. Sign in as two of them and ask the same question to see access control at work.</p>
          <ul>
            {demoAccounts.map((account) => (
              <li key={account.email}>
                <button type="button" onClick={() => { setIdentifier(account.email); setPassword(account.password); setError('') }}>
                  <strong>{account.name}</strong>
                  <span>{account.departments.join(' · ')}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      )}
    </div>
  )
}

export function ChangePassword({ onChange, onLogout, user, dark, setDark }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('')
    try { await onChange(current, next) } catch (failure) { setError(failure.message) } finally { setBusy(false) }
  }
  return (
    <div className="auth single">
      <div className="auth-sheet">
        <header className="auth-brand"><BrandMark size={30} /><span>Meridian</span><ThemeToggle dark={dark} setDark={setDark} /></header>
        <h1>Choose your own password</h1>
        <p className="lede">An administrator created this account for {user.email} with a temporary password. Pick a private one to continue.</p>
        <form onSubmit={submit} className="auth-form">
          <label className="field">Temporary password<input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required /></label>
          <label className="field">New password<input type="password" value={next} onChange={(e) => setNext(e.target.value)} minLength="12" autoComplete="new-password" required /><span className="muted small">At least 12 characters.</span></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button wide" disabled={busy}>{busy ? <><Spinner /> Saving…</> : 'Save and continue'}</button>
        </form>
        <button className="link-button" onClick={onLogout} disabled={busy}>Sign out and use another account</button>
      </div>
    </div>
  )
}

export { ThemeToggle }
