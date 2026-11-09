import { StrictMode, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

function Icon({ name, size = 18 }) {
  const paths = {
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" /></>,
    moon: <path d="M20.4 15.4A8.5 8.5 0 0 1 8.6 3.6 8.5 8.5 0 1 0 20.4 15.4Z" />,
    upload: <><path d="M12 16V3" /><path d="m7 8 5-5 5 5" /><path d="M5 15v4h14v-4" /></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h8M8 17h5" /></>,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function App() {
  const [dark, setDark] = useState(() => localStorage.getItem('meridian-theme') !== 'light')
  const [documents, setDocuments] = useState([])
  const [health, setHealth] = useState('checking')
  const [selectedMode, setSelectedMode] = useState('graph')
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState([])
  const [searching, setSearching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState('')
  const [documentsOpen, setDocumentsOpen] = useState(false)

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('meridian-theme', dark ? 'dark' : 'light')
  }, [dark])

  const loadData = async () => {
    try {
      const [healthResponse, docsResponse] = await Promise.all([fetch(API_BASE + '/health'), fetch(API_BASE + '/documents')])
      setHealth(healthResponse.ok ? 'online' : 'offline')
      if (docsResponse.ok) setDocuments((await docsResponse.json()).documents || [])
    } catch {
      setHealth('offline')
    }
  }

  useEffect(() => { loadData() }, [])

  const stats = useMemo(() => ({
    total: documents.length,
    processed: documents.filter((doc) => doc.status === 'processed').length,
    pending: documents.filter((doc) => doc.status === 'uploaded' || doc.status === 'processing').length,
  }), [documents])

  const upload = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    setNotice('Uploading and processing PDF...')
    const body = new FormData()
    body.append('file', file)
    try {
      const response = await fetch(API_BASE + '/documents/upload', { method: 'POST', body })
      if (!response.ok) throw new Error((await response.json()).detail || 'Upload failed')
      setNotice(file.name + ' is uploaded and processed.')
      await loadData()
    } catch (error) {
      setNotice(error.message)
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  const search = async (event) => {
    event?.preventDefault()
    const prompt = query.trim()
    if (!prompt) return
    setMessages((current) => [...current, { role: 'user', text: prompt }])
    setQuery('')
    setSearching(true)
    try {
      const response = await fetch(API_BASE + '/search?q=' + encodeURIComponent(prompt) + '&mode=' + selectedMode + '&top_k=5')
      if (!response.ok) throw new Error('Search failed')
      const data = await response.json()
      setMessages((current) => [...current, { role: 'assistant', results: data.results || [], mode: selectedMode }])
    } catch (error) {
      setNotice(error.message)
      setMessages((current) => [...current, { role: 'assistant', error: error.message }])
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="chat-app">
      <aside className="chat-sidebar">
        <div className="sidebar-top"><div className="mini-brand"><span className="brand-mark">M</span><span>Meridian</span></div><button className="sidebar-collapse" aria-label="Collapse sidebar">‹</button></div>
        <button className="new-chat-button" onClick={() => { setMessages([]); setQuery('') }}>＋ <span>New chat</span></button>
        <div className="sidebar-section-label">Workspace</div>
        <button className="sidebar-item active"><span className="sidebar-symbol">⌁</span><span>Chat</span></button>
        <button className="sidebar-item" onClick={() => setDocumentsOpen(true)}><Icon name="file" size={16} /><span>Documents</span><small>{stats.processed}</small></button>
        <button className="sidebar-item" onClick={() => { setSelectedMode('graph'); setNotice('Entity graph retrieval is selected.') }}><span className="sidebar-symbol">⌘</span><span>Entity graph</span></button>
        <div className="sidebar-spacer" />
        <div className="sidebar-footer-row"><span className={'connection-dot ' + health} /><span>API {health}</span><button className="icon-button" onClick={() => setDark((value) => !value)} aria-label="Toggle theme"><Icon name={dark ? 'sun' : 'moon'} size={16} /></button></div>
      </aside>

      <div className="chat-stage">
        <main className="chat-main">
          {notice && <div className="notice chat-notice">{notice}<button onClick={() => setNotice('')}>Dismiss</button></div>}
          <section className="conversation">
            <div className="conversation-scroll">
              {messages.length === 0 ? <Welcome /> : messages.map((message, index) => <ChatMessage message={message} key={message.role + '-' + index} />)}
            </div>
            <Composer query={query} setQuery={setQuery} search={search} searching={searching} selectedMode={selectedMode} setSelectedMode={setSelectedMode} upload={upload} uploading={uploading} />
            <p className="composer-hint">Meridian can search processed document chunks. Press Enter to send.</p>
          </section>
        </main>
      </div>

      {documentsOpen && <DocumentDrawer documents={documents} stats={stats} upload={upload} uploading={uploading} close={() => setDocumentsOpen(false)} />}
    </div>
  )
}

function Welcome() {
  return <div className="welcome-screen"><div className="welcome-mark">M</div><h1>What can I help you find?</h1><p>Ask Meridian about your processed documents.</p><div className="welcome-suggestions"><span>What is a semaphore?</span><span>Explain deadlock prevention.</span></div></div>
}

function Composer({ query, setQuery, search, searching, selectedMode, setSelectedMode, upload, uploading }) {
  return <form onSubmit={search} className="chatgpt-composer"><textarea value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); search(event) } }} placeholder="Message Meridian..." rows="1" /><div className="composer-toolbar"><div className="composer-left"><label className="attach-button" title="Upload PDF">＋<input type="file" accept="application/pdf,.pdf" onChange={upload} disabled={uploading} /></label><div className="composer-modes">{['graph', 'bm25', 'dense', 'hybrid'].map((mode) => <button type="button" key={mode} className={selectedMode === mode ? 'composer-mode active' : 'composer-mode'} onClick={() => setSelectedMode(mode)}>{mode === 'graph' ? 'Entity graph' : mode.toUpperCase()}</button>)}</div></div><button className="send-button" type="submit" disabled={searching || !query.trim()} aria-label="Send message"><Icon name="arrow" size={17} /></button></div></form>
}

function ChatMessage({ message }) {
  if (message.role === 'user') return <div className="message user-message"><div className="user-bubble">{message.text}</div></div>
  return <div className="message assistant-message"><div className="assistant-mark">M</div><div className="assistant-body">{message.error ? <p className="error-text">{message.error}</p> : <><div className="answer-label">Retrieved with {message.mode === 'graph' ? 'Entity graph' : message.mode.toUpperCase()}</div>{message.results.length === 0 ? <p className="empty-answer">No matching chunks were found.</p> : <div className="results">{message.results.map((result, index) => <ResultCard result={result} index={index} key={result.chunk_id + '-' + index} />)}</div>}</>}</div></div>
}

function ResultCard({ result, index }) {
  return <article className="result-card"><div className="result-meta"><span className="result-index">0{index + 1}</span><span>{result.filename || 'Document'}</span><span>Page {result.page_number}</span><span className="score">{result.graph_score ? 'Score ' + result.graph_score.toFixed(2) : 'Matched'}</span></div><p>{result.text}</p>{result.matched_entities && <div className="entity-tags">{result.matched_entities.slice(0, 4).map((entity) => <span key={entity.id}>{entity.name}</span>)}</div>}</article>
}

function DocumentDrawer({ documents, stats, upload, uploading, close }) {
  return <><button className="drawer-backdrop" onClick={close} aria-label="Close documents" /><aside className="document-drawer"><div className="drawer-header"><div><span className="eyebrow">Knowledge sources</span><h2>Documents</h2><small>{stats.processed} processed · {stats.pending} pending</small></div><button className="icon-button" onClick={close} aria-label="Close"><Icon name="close" size={18} /></button></div><label className="drawer-upload"><Icon name="upload" size={16} /> {uploading ? 'Processing...' : 'Upload PDF'}<input type="file" accept="application/pdf,.pdf" onChange={upload} disabled={uploading} /></label><div className="drawer-list">{documents.length === 0 ? <div className="drawer-empty">No documents yet.</div> : documents.map((doc) => <div className="drawer-document" key={doc.id}><div className="drawer-file"><Icon name="file" size={16} /></div><div><strong>{doc.filename}</strong><small>Document {doc.id} · {formatBytes(doc.file_size)}</small></div><span className={'badge ' + doc.status}>{doc.status}</span></div>)}</div></aside></>
}

function formatBytes(bytes = 0) { if (bytes < 1024) return bytes + ' B'; if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB'; return (bytes / 1024 / 1024).toFixed(1) + ' MB' }

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)

