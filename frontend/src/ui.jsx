import { Fragment } from 'react'

const PATHS = {
  chat: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4H6.5A2.5 2.5 0 0 1 4 12.5Z" /></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h8M8 17h5" /></>,
  graph: <><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="m8.3 10.8 7.4-3.6M8.3 13.2l7.4 3.6" /></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  arrowUp: <path d="M12 19V5m-6 6 6-6 6 6" />,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  upload: <><path d="M12 16V3" /><path d="m7 8 5-5 5 5" /><path d="M5 15v4h14v-4" /></>,
  download: <><path d="M12 3v13" /><path d="m7 11 5 5 5-5" /><path d="M5 21h14" /></>,
  moon: <path d="M20.4 15.4A8.5 8.5 0 0 1 8.6 3.6 8.5 8.5 0 1 0 20.4 15.4Z" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  shield: <><path d="M12 3 19 6v5c0 4.6-3 8.2-7 10-4-1.8-7-5.4-7-10V6Z" /><path d="m9 12 2 2 4-4" /></>,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
  refresh: <><path d="M20 11a8 8 0 0 0-14.7-4L4 9" /><path d="M4 4v5h5M4 13a8 8 0 0 0 14.7 4L20 15" /><path d="M20 20v-5h-5" /></>,
  panel: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>,
  stop: <rect x="7" y="7" width="10" height="10" rx="1.5" />,
  logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5M21 12H9" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  check: <path d="m5 12 5 5 9-10" />,
  edit: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></>,
}

export function Icon({ name, size = 18, label }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden={label ? undefined : 'true'} role={label ? 'img' : undefined} aria-label={label}>
      {PATHS[name]}
    </svg>
  )
}

export function BrandMark({ size = 28 }) {
  // A meridian line crossing a page: the product's own mark, drawn not lettered.
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="5" y="3" width="22" height="26" rx="3" fill="var(--sheet)" stroke="var(--ink)" strokeWidth="1.6" />
      <path d="M10 10h12M10 15h8M10 20h10" stroke="var(--ink-3)" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M16 1v30" stroke="var(--mark)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

/* ---------------------------------------------------------------- answers */

const CITE_RE = /\[(C\d+(?:\s*,\s*C\d+)*)\]|\((C\d+(?:\s*,\s*C\d+)*)\)/g

function inline(text, keyPrefix, onCite, activeCite, citeNumber) {
  const out = []
  let last = 0
  let match
  CITE_RE.lastIndex = 0
  while ((match = CITE_RE.exec(text))) {
    if (match.index > last) out.push(...bold(text.slice(last, match.index), `${keyPrefix}-t${last}`))
    const ids = (match[1] || match[2]).split(/\s*,\s*/)
    ids.forEach((id) => {
      const n = citeNumber(id)
      out.push(
        <button type="button" key={`${keyPrefix}-c${match.index}-${id}`} className={'cite' + (activeCite === id ? ' is-active' : '')}
          onMouseEnter={() => onCite?.(id, 'hover')} onMouseLeave={() => onCite?.(null, 'hover')} onFocus={() => onCite?.(id, 'hover')}
          onBlur={() => onCite?.(null, 'hover')} onClick={() => onCite?.(id, 'open')} aria-label={`Source ${n}`}>{n}</button>,
      )
    })
    last = match.index + match[0].length
  }
  if (last < text.length) out.push(...bold(text.slice(last), `${keyPrefix}-t${last}`))
  return out
}

function bold(text, key) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong> : <Fragment key={`${key}-${i}`}>{part}</Fragment>,
  )
}

/** Render model text: paragraphs, bullet and numbered lists, **bold**, and [C1] citation markers. */
export function AnswerText({ text, onCite, activeCite, citeNumber = (id) => id.slice(1) }) {
  const blocks = []
  let list = null
  text.replace(/\r/g, '').split('\n').forEach((rawLine, index) => {
    const line = rawLine.trim()
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/)
    if (bullet) {
      const ordered = /^\d/.test(line)
      if (!list || list.ordered !== ordered) { list = { ordered, items: [] }; blocks.push(list) }
      list.items.push({ text: bullet[1], key: index })
      return
    }
    list = null
    if (line) blocks.push({ text: line, key: index })
  })
  return (
    <div className="answer-text">
      {blocks.map((block, i) => {
        if (block.items) {
          const Tag = block.ordered ? 'ol' : 'ul'
          return <Tag key={`b${i}`}>{block.items.map((item) => <li key={item.key}>{inline(item.text, `l${item.key}`, onCite, activeCite, citeNumber)}</li>)}</Tag>
        }
        return <p key={`b${i}`}>{inline(block.text, `p${block.key}`, onCite, activeCite, citeNumber)}</p>
      })}
    </div>
  )
}
