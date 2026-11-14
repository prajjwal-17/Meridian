import { useState } from 'react'
import { apiJson, documentTitle } from './api'
import { Icon, Spinner } from './ui'

export function GraphWorkspace({ onAsk }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const explore = async (event) => {
    event.preventDefault()
    const prompt = query.trim()
    if (!prompt || busy) return
    setBusy(true); setError('')
    try {
      const data = await apiJson(`/search?${new URLSearchParams({ q: prompt, mode: 'graph', top_k: '8' })}`)
      setResults(data.results || [])
    } catch (failure) { setError(failure.message); setResults(null) } finally { setBusy(false) }
  }

  const list = results || []
  const entities = [...new Map(list.flatMap((r) => [...(r.matched_entities || []), ...(r.entities || [])]).map((e) => [e.id, e])).values()]
  const relationships = [...new Map(list.flatMap((r) => r.relationships || []).map((e) => [`${e.source_entity_id}-${e.target_entity_id}-${e.relationship_type}`, e])).values()]
  const names = new Map(entities.map((e) => [e.id, e.name]))

  return (
    <section className="page" aria-label="Entity graph">
      <header className="page-head">
        <div>
          <p className="kicker">Explore</p>
          <h1>Entity graph</h1>
          <p className="lede">Find the systems, teams and concepts named in your documents, and how they connect. Only passages you can read are searched.</p>
        </div>
      </header>
      <form className="graph-search" onSubmit={explore}>
        <label className="search-field large"><Icon name="search" size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. PostgreSQL, API Gateway, payroll" aria-label="Entity or concept" />
        </label>
        <button className="primary-button" disabled={busy || !query.trim()}>{busy ? <><Spinner /> Exploring…</> : 'Explore'}</button>
        {results && query.trim() && <button type="button" className="ghost-button" onClick={() => onAsk(query.trim())}>Ask about this <Icon name="arrow" size={15} /></button>}
      </form>
      {error && <p className="form-error">{error}</p>}
      {results === null && !error && <div className="empty"><Icon name="graph" size={26} /><p>Type an entity or concept to see where it appears.</p></div>}
      {results && results.length === 0 && <div className="empty"><p>No entities matched “{query}” in the documents you can read.</p></div>}
      {list.length > 0 && (
        <div className="graph-results">
          <section className="panel">
            <div className="panel-title"><h2>{entities.length} entities</h2><p className="muted">{relationships.length} typed relationships</p></div>
            <div className="entity-cloud">{entities.map((e) => <span className="entity" key={e.id}>{e.name}<small>{e.entity_type}</small></span>)}</div>
            {relationships.length > 0 && (
              <ul className="relations">
                {relationships.slice(0, 24).map((edge) => (
                  <li key={`${edge.source_entity_id}-${edge.target_entity_id}-${edge.relationship_type}`}>
                    <span>{names.get(edge.source_entity_id) || edge.source_entity_id}</span><span className="rel">{edge.relationship_type.replace(/_/g, ' ')}</span><span>{names.get(edge.target_entity_id) || edge.target_entity_id}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel">
            <div className="panel-title"><h2>Where they appear</h2></div>
            <ol className="sources plain">
              {list.map((r, i) => (
                <li className="source" key={`${r.chunk_id}-${i}`}>
                  <div className="source-head"><span className="source-num">{i + 1}</span><div><strong>{documentTitle(r)}</strong><span className="mono">{r.page_number ? `page ${r.page_number}` : `chunk ${r.chunk_id}`}</span></div></div>
                  <blockquote className="clamp">{r.text}</blockquote>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </section>
  )
}
