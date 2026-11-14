import { useEffect, useMemo, useRef, useState } from 'react'
import { apiJson, documentTitle, streamAnswer } from './api'
import { AnswerText, Icon, Spinner } from './ui'

const MODES = [
  { id: 'hybrid', label: 'Hybrid', hint: 'Keyword + semantic search, reranked (recommended)' },
  { id: 'dense', label: 'Semantic', hint: 'Meaning-based vector search' },
  { id: 'bm25', label: 'Keyword', hint: 'Exact-term BM25 search' },
  { id: 'graph', label: 'Graph', hint: 'Entity graph traversal' },
]

function suggestionFor(title) {
  const name = title.replace(/^[A-Z]{2,4}-\d{3}\s*/, '').trim()
  if (/policy|standards|procedures|framework|plan|agreement|sop/i.test(name)) return `What does the ${name} require?`
  return `What are the key points of the ${name}?`
}

export function ChatWorkspace({ user, access, onNotice }) {
  const [messages, setMessages] = useState([])
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [busy, setBusy] = useState(false)
  const [activeIndex, setActiveIndex] = useState(null)
  const [focusCite, setFocusCite] = useState(null)
  // The evidence margin sits beside the answer on wide screens; on narrower
  // ones it would cover the answer, so it opens only when a citation is tapped.
  const wide = () => window.matchMedia('(min-width: 1181px)').matches
  const [railOpen, setRailOpen] = useState(wide)
  const abortRef = useRef(null)
  const threadRef = useRef(null)
  const inputRef = useRef(null)

  const suggestions = useMemo(() => {
    const docs = (access.documents || []).filter((doc) => doc.status === 'processed')
    return docs.slice(0, 4).map((doc) => suggestionFor(documentTitle(doc)))
  }, [access.documents])

  useEffect(() => { inputRef.current?.focus() }, [])
  useEffect(() => {
    const el = threadRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: busy ? 'auto' : 'smooth' })
  }, [messages, busy])

  const active = activeIndex !== null ? messages[activeIndex] : null

  const update = (index, patch) => setMessages((current) => current.map((m, i) => (i === index ? { ...m, ...patch(m) } : m)))

  const ask = async (prompt, askMode = mode) => {
    const question = prompt.trim()
    if (!question || busy) return
    setQuery('')
    setBusy(true)
    const userIndex = messages.length
    const answerIndex = userIndex + 1
    setMessages((current) => [...current, { role: 'user', text: question }, { role: 'assistant', mode: askMode, stage: 'retrieving', text: '', passages: [], citations: [] }])
    setActiveIndex(answerIndex)
    setFocusCite(null)
    if (!wide()) setRailOpen(false)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await streamAnswer({ question, mode: askMode, top_k: 5, rerank: true }, (event) => {
        if (event.type === 'retrieval') {
          update(answerIndex, () => ({ passages: event.passages, candidates: event.retrieval.candidate_result_count, stage: event.passages.length ? 'writing' : 'final' }))
        } else if (event.type === 'token') {
          update(answerIndex, (m) => ({ text: m.text + event.text }))
        } else if (event.type === 'final') {
          update(answerIndex, () => ({ stage: 'final', text: event.answer, citations: event.citations, sufficient: event.sufficient_evidence }))
        } else if (event.type === 'error') {
          update(answerIndex, () => ({ stage: 'error', error: event.detail }))
        }
      }, controller.signal)
    } catch (error) {
      if (error.name === 'AbortError') update(answerIndex, (m) => ({ stage: 'stopped', text: m.text }))
      else { update(answerIndex, () => ({ stage: 'error', error: error.message })); onNotice?.(error.message) }
    } finally {
      setBusy(false)
      abortRef.current = null
      inputRef.current?.focus()
    }
  }

  const onCite = (index) => (id, kind) => {
    setActiveIndex(index)
    setFocusCite(id)
    if (kind === 'open') {
      setRailOpen(true)
      requestAnimationFrame(() => document.getElementById(`source-${index}-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
    }
  }

  const askRef = useRef(ask)
  askRef.current = ask
  useEffect(() => {
    const handler = (event) => askRef.current(event.detail)
    window.addEventListener('meridian:ask', handler)
    return () => window.removeEventListener('meridian:ask', handler)
  }, [])

  const reset = () => { abortRef.current?.abort(); setMessages([]); setActiveIndex(null); setFocusCite(null); inputRef.current?.focus() }

  return (
    <div className={'chat-layout' + (railOpen && active ? ' with-rail' : '')}>
      <section className="chat-column" aria-label="Ask Meridian">
        <header className="chat-bar">
          <div className="reading-as" title="Answers only use documents this account can read">
            <Icon name="lock" size={15} />
            <span>Reading as <strong>{user.name}</strong></span>
            <span className="muted">· {access.documents ? `${access.documents.length} documents` : '…'}</span>
          </div>
          <div className="chat-bar-actions">
            {messages.length > 0 && <button className="ghost-button" onClick={reset}><Icon name="plus" size={15} /> New question</button>}
            {active && <button className="ghost-button sources-toggle" onClick={() => setRailOpen((open) => !open)} aria-pressed={railOpen} title={railOpen ? 'Hide sources' : 'Show sources'}><Icon name="panel" size={16} /> Sources{active.passages?.length ? ` (${active.passages.length})` : ''}</button>}
          </div>
        </header>

        <div className="thread" ref={threadRef}>
          {messages.length === 0 ? (
            <Welcome user={user} suggestions={suggestions} onPick={(text) => ask(text)} documentCount={access.documents?.length} />
          ) : (
            messages.map((message, index) => message.role === 'user'
              ? <div className="question" key={index}><p>{message.text}</p></div>
              : <Answer key={index} message={message} isActive={index === activeIndex} focusCite={index === activeIndex ? focusCite : null}
                  onCite={onCite(index)} onSelect={() => setActiveIndex(index)} />)
          )}
        </div>

        <form className="composer" onSubmit={(event) => { event.preventDefault(); ask(query) }}>
          <textarea ref={inputRef} value={query} rows={1} onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); ask(query) } }}
            placeholder="Ask about a policy, process or standard…" aria-label="Your question" />
          <div className="composer-row">
            <label className="mode-select" title={MODES.find((m) => m.id === mode)?.hint}>
              <span>Search</span>
              <select value={mode} onChange={(event) => setMode(event.target.value)} aria-label="Retrieval mode">
                {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
            <span className="composer-hint">Enter to ask · Shift+Enter for a new line</span>
            {busy
              ? <button type="button" className="send is-stop" onClick={() => abortRef.current?.abort()} aria-label="Stop answering"><Icon name="stop" size={16} /></button>
              : <button type="submit" className="send" disabled={!query.trim()} aria-label="Ask"><Icon name="arrowUp" size={18} /></button>}
          </div>
        </form>
      </section>

      {active && railOpen && <EvidenceRail message={active} index={activeIndex} focusCite={focusCite} setFocusCite={setFocusCite} onClose={() => setRailOpen(false)} />}
    </div>
  )
}

function Welcome({ user, suggestions, onPick, documentCount }) {
  const first = user.name.split(' ')[0]
  return (
    <div className="welcome">
      <p className="kicker">Meridian</p>
      <h1>What do you need to check, {first}?</h1>
      <p className="lede">Answers come only from the {documentCount ?? ''} documents your account can read, and every sentence points to the page it came from.</p>
      {suggestions.length > 0 && (
        <div className="suggestions">
          {suggestions.map((text, i) => (
            <button key={text} onClick={() => onPick(text)} style={{ '--i': i }}><span>{text}</span><Icon name="arrow" size={15} /></button>
          ))}
        </div>
      )}
    </div>
  )
}

const STAGE_LABEL = {
  retrieving: 'Searching your documents…',
  writing: 'Writing the answer…',
}

function Answer({ message, isActive, focusCite, onCite, onSelect }) {
  const cited = new Set((message.citations || []).map((c) => c.citation_id))
  const sourcesUsed = message.stage === 'final' ? cited.size : message.passages.length
  return (
    <article className={'answer' + (isActive ? ' is-active' : '')} onClick={onSelect}>
      {(message.stage === 'retrieving' || message.stage === 'writing') && (
        <div className="stage" aria-live="polite"><Spinner /> {STAGE_LABEL[message.stage]}
          {message.stage === 'writing' && message.passages.length > 0 && <span className="muted"> from {message.passages.length} passage{message.passages.length > 1 ? 's' : ''}</span>}
        </div>
      )}
      {message.stage === 'error' && <p className="answer-error">{message.error}</p>}
      {message.text && <AnswerText text={message.text.replace(/INSUFFICIENT_EVIDENCE/g, '')} onCite={onCite} activeCite={focusCite} />}
      {message.stage === 'stopped' && <p className="muted small">Stopped.</p>}
      {message.stage === 'final' && (
        <footer className="answer-meta">
          {message.sufficient
            ? <span className="evidence ok"><Icon name="check" size={14} /> Grounded in {sourcesUsed} source{sourcesUsed === 1 ? '' : 's'}</span>
            : <span className="evidence none">No supporting passage found</span>}
          <span className="muted">{({ hybrid: 'Hybrid', dense: 'Semantic', bm25: 'Keyword', graph: 'Graph' })[message.mode]} search</span>
        </footer>
      )}
    </article>
  )
}

function EvidenceRail({ message, index, focusCite, setFocusCite, onClose }) {
  const cited = new Set((message.citations || []).map((c) => c.citation_id))
  const final = message.stage === 'final'
  const passages = message.passages || []
  const ordered = final ? [...passages].sort((a, b) => Number(cited.has(b.citation_id)) - Number(cited.has(a.citation_id))) : passages
  return (
    <aside className="rail" aria-label="Sources for this answer">
      <header className="rail-head">
        <div>
          <p className="kicker">Evidence</p>
          <h2>{passages.length ? `${final ? cited.size : passages.length} of ${passages.length} passages ${final ? 'cited' : 'selected'}` : 'No passages selected'}</h2>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Hide sources"><Icon name="close" size={16} /></button>
      </header>
      {passages.length === 0 && message.stage !== 'retrieving' && (
        <p className="rail-empty">Nothing in the documents you can read was relevant enough to quote. Try naming the policy or document you have in mind.</p>
      )}
      <ol className="sources">
        {ordered.map((passage) => {
          const used = !final || cited.has(passage.citation_id)
          const on = focusCite === passage.citation_id
          return (
            <li key={passage.citation_id} id={`source-${index}-${passage.citation_id}`}
              className={'source' + (used ? '' : ' is-unused') + (on ? ' is-focus' : '')}
              onMouseEnter={() => setFocusCite(passage.citation_id)} onMouseLeave={() => setFocusCite(null)}>
              <div className="source-head">
                <span className="source-num">{passage.citation_id.slice(1)}</span>
                <div>
                  <strong>{documentTitle(passage)}</strong>
                  <span className="mono">{passage.source_document_id ? `${passage.source_document_id} · ` : ''}{passage.page_number ? `page ${passage.page_number}` : `chunk ${passage.chunk_id}`}</span>
                </div>
                <a className="icon-button" href={`/api/documents/${passage.document_id}/download`} aria-label="Download source PDF" title="Download source PDF"><Icon name="download" size={15} /></a>
              </div>
              <details open={on || undefined}>
                <summary>{used ? (final ? 'Quoted passage' : 'Passage') : 'Retrieved, not cited'}</summary>
                <blockquote>{passage.text}</blockquote>
              </details>
            </li>
          )
        })}
      </ol>
    </aside>
  )
}
