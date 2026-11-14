export const API_BASE = import.meta.env.VITE_API_URL || '/api'

export function csrfToken() {
  return document.cookie.split('; ').find((item) => item.startsWith('meridian_csrf='))?.split('=')[1] || ''
}

export async function apiFetch(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const headers = new Headers(options.headers || {})
  if (!['GET', 'HEAD'].includes(method)) headers.set('X-CSRF-Token', csrfToken())
  return fetch(API_BASE + path, { ...options, method, headers, credentials: 'include' })
}

export async function apiJson(path, options = {}) {
  const init = { ...options }
  if (init.body !== undefined && !(init.body instanceof FormData) && typeof init.body !== 'string') {
    init.body = JSON.stringify(init.body)
    init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) }
  }
  const response = await apiFetch(path, init)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join('; ') : data.detail
    throw new Error(detail || `Request failed (HTTP ${response.status}).`)
  }
  return data
}

/**
 * Ask a question and receive the answer as it is written.
 * onEvent receives {type: 'retrieval' | 'token' | 'final' | 'error', ...}.
 */
export async function streamAnswer(body, onEvent, signal) {
  const response = await apiFetch('/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || `Meridian could not answer (HTTP ${response.status}).`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let newline
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).trim()
      buffer = buffer.slice(newline + 1)
      if (line) onEvent(JSON.parse(line))
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer))
}

export function documentTitle(item) {
  const raw = item?.filename || item?.source_document_id || `Document ${item?.document_id ?? ''}`
  return String(raw).replace(/\.pdf$/i, '').replace(/\.p$/i, '').replace(/_/g, ' ').replace(/\s+/g, ' ').trim()
}

export function aclLabel(doc) {
  const list = (values, single) => (values?.length ? values : single ? [single] : [])
  switch (doc.permission_tier) {
    case 'public': return 'Everyone'
    case 'department': return list(doc.permission_departments, doc.permission_department).join(', ') || 'Department'
    case 'team': return list(doc.permission_teams, doc.permission_team).join(', ') || 'Team'
    case 'restricted': return 'Named people only'
    default: return 'Unclassified'
  }
}
