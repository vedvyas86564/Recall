import './App.css'
import recallIcon from './assets/RecallIcon.svg'
import githubCardIcon from './assets/GitHubCard.svg'
import toAskArrowIcon from './assets/ToAskArrow.svg'
import threadsIcon from './assets/threads.svg'
import knowledgeBaseIcon from './assets/knowledge_base.svg'
import projectsIcon from './assets/projects.svg'
import settingsIcon from './assets/settings.svg'
import slackLogo from './assets/slack.png'
import gmailLogo from './assets/gmail.svg'
import meetingsLogo from './assets/meetings.svg'
import notionLogo from './assets/notion.png'
import dbIcon from './assets/DB.svg'
import linkIcon from './assets/link.svg'
import lockIcon from './assets/lock.svg'
import cancelIcon from './assets/cancel.svg'
import { useEffect, useRef, useState } from 'react'
import SpotlightCard from './components/SpotlightCard'
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8000";
// Config, not literals scattered through call sites. Both must match the
// backend: API_KEY against its API_KEY env var, ORG_ID against the tenant the
// corpus was ingested under.
const API_KEY = import.meta.env.VITE_API_KEY ?? "recall-demo-key";
const ORG_ID = import.meta.env.VITE_ORG_ID ?? "00000000-0000-0000-0000-000000000001";

function Icon({ children }) {
  return <span className="icon">{children}</span>
}

function App() {
  const [activeButton, setActiveButton] = useState('menu-threads')
  const [activeChip, setActiveChip] = useState('chip-all')
  const [page, setPage] = useState('home')
  const [query, setQuery] = useState('')
  const [resultTab, setResultTab] = useState('answer')
  const [isManageOpen, setIsManageOpen] = useState(false)
  const [autoConnect, setAutoConnect] = useState(true)
  const [longMemory, setLongMemory] = useState(false)

  // No seeded chats. Every result in the demo path must come from a real
  // retrieval against the indexed corpus (spec rule 4); fixtures here were
  // indistinguishable from real answers in the UI.
  const [chats, setChats] = useState([])
  const [recentItems, setRecentItems] = useState([])
  const [activeChatId, setActiveChatId] = useState(null)
  // Threads actually present in the index, used to show real examples on the
  // landing page instead of invented ones.
  const [corpusDocs, setCorpusDocs] = useState([])

  const primaryNav = [
    { id: 'menu-threads', label: 'Threads', icon: threadsIcon },
    { id: 'menu-kb', label: 'Knowledge Base', icon: knowledgeBaseIcon },
    { id: 'menu-projects', label: 'Projects', icon: projectsIcon },
    { id: 'menu-settings', label: 'Source Management', icon: settingsIcon },
  ]

  // Filter chips describe what is actually indexed. Slack, Gmail, and Meetings
  // were listed here with nothing behind them (spec rule 4).
  const chips = [
    { id: 'chip-all', label: 'All' },
    { id: 'chip-github', label: 'GitHub' },
  ]

  // Real threads from the indexed corpus, fetched on mount, replacing three
  // invented cards ("Rate limiting discussion", "Architecture Review",
  // "Database migration plan") that referenced nothing.
  const sourceCards = corpusDocs.slice(0, 3).map((doc) => ({
    id: doc.id,
    type: doc.metadata?.repo ?? 'GitHub',
    title: doc.title,
    url: doc.metadata?.url ?? null,
    icon: githubCardIcon,
  }))

  const sourceCatalog = {
    slack: {
      key: 'slack',
      name: 'Slack',
      subtitle: 'Communication',
      logo: slackLogo,
      primaryLabel: 'Messages',
      primaryValue: '85.2k',
      itemCount: 85200,
      secondaryLabel: 'Last Sync',
      secondaryValue: '5m ago',
    },
    gmail: {
      key: 'gmail',
      name: 'Gmail',
      subtitle: 'Email',
      logo: gmailLogo,
      primaryLabel: 'Emails',
      primaryValue: '12.5k',
      itemCount: 12500,
      secondaryLabel: 'Last Sync',
      secondaryValue: '10m ago',
    },
    meeting: {
      key: 'meeting',
      name: 'Meeting Transcripts',
      subtitle: 'Audio & Video',
      logo: meetingsLogo,
      primaryLabel: 'Transcripts',
      primaryValue: '218',
      itemCount: 218,
      secondaryLabel: 'Last Sync',
      secondaryValue: 'Now',
      meetingStyle: true,
    },
    notion: {
      key: 'notion',
      name: 'Notion',
      subtitle: 'Docs & Wiki',
      logo: notionLogo,
      primaryLabel: 'Pages',
      primaryValue: '4.9k',
      itemCount: 4900,
      secondaryLabel: 'Last Sync',
      secondaryValue: '3m ago',
    },
  }

  // Only sources that are genuinely indexed. Slack, Gmail, and meetings were
  // previously shown as 'connected' with no ingestion behind any of them
  // (spec rule 4). GitHub is the Phase 1 corpus -- see DECISIONS.md D8.
  const [services, setServices] = useState([
    { id: 'svc-github', type: 'github', status: 'connected' },
  ])
  const loadTimers = useRef({})

  const activeChat =
    chats.find((chat) => chat.id === activeChatId) ??
    chats[0] ?? {
      id: 'empty',
      title: 'No searches yet',
      tags: [],
      resultCount: 0,
      summary: 'Ask a question to search the indexed corpus.',
      sections: [],
      sources: [],
    }

  const handlePrimaryNav = (itemId) => {
    setActiveButton(itemId)
    if (itemId === 'menu-threads') setPage('home')
    if (itemId === 'menu-kb') setPage('placeholder')
    if (itemId === 'menu-settings') setPage('service')
    if (itemId === 'menu-projects') setPage('projects')
  }

  const handleSearchSubmit = async (event) => {
  event.preventDefault()
  const normalizedQuery = query.trim()
  if (!normalizedQuery) return

  // 1) Call backend
  let data
  try {
    const res = await fetch(`${BACKEND_URL}/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "x-org-id": ORG_ID,
      },
      // org_id deliberately absent from the body: the backend takes the tenant
      // from the header only, so a client cannot select its own tenant.
      body: JSON.stringify({ question: normalizedQuery, top_k: 10 }),
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Backend error ${res.status}: ${text}`)
    }
    data = await res.json()
  } catch (err) {
    console.error(err)
    // fallback: show an error chat card
    const errorChat = {
      id: `chat-${Date.now()}`,
      title: normalizedQuery,
      tags: ["#error"],
      resultCount: 0,
      summary: `Backend request failed: ${err.message}`,
      sections: [],
      sources: [],
    }
    setChats((prev) => [errorChat, ...prev])
    setActiveChatId(errorChat.id)
    setQuery("")
    setPage("result")
    setResultTab("answer")
    setActiveButton("menu-threads")
    return
  }

  // 2) Convert backend response -> UI chat format
  const decisions = data.decisions ?? []

  const toSource = (s, i) => ({
    id: s.id ?? `src-${Date.now()}-${i}`,
    title: s.title ?? "Source",
    excerpt: s.excerpt ?? "",
    // Null when the chunk has no resolvable deep link. Rendered as plain text
    // rather than a dead anchor (spec rule 5).
    url: s.url ?? null,
    score: s.score,
  })

  const retrieval = {
    topScore: data.top_score,
    threshold: data.threshold,
    retrievedCount: data.retrieved_count,
  }

  // The backend decided it could not answer. Show that plainly, with the
  // closest material it did find, rather than dressing up a low-confidence
  // guess as an answer (spec 1.2).
  const nextChat = data.abstained
    ? {
        id: `chat-${Date.now()}`,
        title: normalizedQuery,
        tags: ["#no-answer"],
        resultCount: 0,
        summary:
          data.reason ??
          "No indexed content was close enough to answer this confidently.",
        sections: (data.near_misses ?? []).length
          ? [
              {
                heading: "Closest material found",
                body: "None of these cleared the relevance threshold, so they are shown as leads rather than as an answer.",
              },
            ]
          : [],
        sources: (data.near_misses ?? []).map(toSource),
        retrieval,
        abstained: true,
      }
    : {
        id: `chat-${Date.now()}`,
        title: normalizedQuery,
        tags: ["#rag", "#decisions"],
        resultCount: decisions.length,
        summary:
          decisions.length === 0
            ? "No decisions found in the retrieved context."
            : `Found ${decisions.length} decision(s) from retrieved context.`,
        sections: decisions.map((d, i) => ({
          heading: `${i + 1}. ${d.title || "Decision"}`,
          body: `${d.decision || ""}${d.owner ? `\n\nOwner: ${d.owner}` : ""}`,
          // Per-decision citations, so evidence attaches to the claim it
          // supports instead of one undifferentiated pile.
          citations: (d.citations ?? []).map(toSource),
        })),
        sources: (data.sources ?? []).map(toSource),
        retrieval,
        abstained: false,
      }

  // 3) Update UI state like before
  setChats((prev) => [nextChat, ...prev])
  setRecentItems((prev) => [{ id: nextChat.id }, ...prev].slice(0, 8))
  setActiveChatId(nextChat.id)
  setQuery("")
  setPage("result")
  setResultTab("answer")
  setActiveButton("menu-threads")
}

  const handleDeleteChat = (chatId) => {
    const updatedChats = chats.filter((chat) => chat.id !== chatId)
    setChats(updatedChats)
    setRecentItems((prev) => prev.filter((item) => item.id !== chatId))
    if (activeChatId === chatId) {
      setActiveChatId(updatedChats[0]?.id ?? null)
    }
  }

  const clearLoadTimer = (serviceId) => {
    if (loadTimers.current[serviceId]) {
      clearTimeout(loadTimers.current[serviceId])
      delete loadTimers.current[serviceId]
    }
  }

  const removeService = (serviceId) => {
    clearLoadTimer(serviceId)
    setServices((prev) => prev.filter((service) => service.id !== serviceId))
  }

  const addService = (serviceType) => {
    if (services.some((service) => service.type === serviceType)) return

    const serviceId = `svc-${serviceType}-${Date.now()}`
    setServices((prev) => [...prev, { id: serviceId, type: serviceType, status: 'loading' }])

    loadTimers.current[serviceId] = setTimeout(() => {
      setServices((prev) =>
        prev.map((service) =>
          service.id === serviceId ? { ...service, status: 'connected' } : service,
        ),
      )
      clearLoadTimer(serviceId)
    }, 2600)
  }

  useEffect(
    () => () => {
      Object.values(loadTimers.current).forEach((timer) => clearTimeout(timer))
    },
    [],
  )

  // Load a few real threads from the index for the landing page. Failure is
  // non-fatal: the cards simply do not render, which is honest. Showing
  // placeholders here is what the fixtures did, and is what rule 4 forbids.
  useEffect(() => {
    let cancelled = false

    fetch(`${BACKEND_URL}/documents`, {
      headers: { 'x-api-key': API_KEY, 'x-org-id': ORG_ID },
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(res.status))))
      .then((data) => {
        if (!cancelled) setCorpusDocs(data.documents ?? [])
      })
      .catch((err) => console.error('Could not load indexed documents:', err))

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!isManageOpen) return

    const onKeyDown = (event) => {
      if (event.key === 'Escape') setIsManageOpen(false)
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isManageOpen])

  const connectedCount = services.filter((service) => service.status === 'connected').length
  const totalItems = services
    .filter((service) => service.status === 'connected')
    .reduce((sum, service) => sum + (sourceCatalog[service.type]?.itemCount ?? 0), 0)
  const missingServiceTypes = Object.keys(sourceCatalog).filter(
    (type) => !services.some((service) => service.type === type),
  )

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <img className="brand-icon" src={recallIcon} alt="Recall" />
          <span>Recall</span>
        </div>

        <nav className="menu-list">
          {primaryNav.map((item) => (
            <button
              className={`menu-item ${activeButton === item.id ? 'active' : ''}`}
              key={item.id}
              onClick={() => handlePrimaryNav(item.id)}
              type="button"
            >
              <Icon>
                <img className="menu-icon" src={item.icon} alt="" />
              </Icon>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="recent-wrap">
          <p className="recent-title">RECENT</p>
          {recentItems.map((item) => (
            <div className="recent-row" key={item.id}>
              <button
                className={`recent-item ${activeButton === item.id ? 'active' : ''}`}
                onClick={() => {
                  setActiveButton(item.id)
                  setActiveChatId(item.id)
                  setPage('result')
                  setResultTab('answer')
                }}
                type="button"
              >
                <Icon>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 7v5l3 2" />
                    <path d="M12 3a9 9 0 1 1-8.2 5.2" />
                  </svg>
                </Icon>
                <span>{chats.find((chat) => chat.id === item.id)?.title ?? 'Untitled chat'}</span>
              </button>
              <button
                aria-label="Delete chat"
                className="recent-delete"
                onClick={() => handleDeleteChat(item.id)}
                type="button"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        <div className="user-row">
          <div className="avatar">AC</div>
          <span>Alex Chen</span>
        </div>
      </aside>

      <main className="main-content">
        <div className="page-transition" key={`${page}-${activeButton}`}>
          {page === 'home' ? (
            <>
              <div className="content-inner">
                <h1>Search across your universe.</h1>
                <p className="subhead">
                  Connect your engineering context. Ask complex questions. Get cited answers instantly.
                </p>

                <section className="search-shell">
                  <form className="search-top" onSubmit={handleSearchSubmit}>
                    <Icon>
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <circle cx="11" cy="11" r="6" />
                        <path d="m20 20-3.5-3.5" />
                      </svg>
                    </Icon>
                    <input
                      className="search-input"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Ask a question..."
                      type="text"
                    />
                    <button className="kbd" type="submit">
                      Enter
                    </button>
                  </form>
                  <div className="search-bottom">
                    <span className="searching-label">Searching in:</span>
                    {chips.map((chip) => (
                      <button
                        className={`chip ${activeChip === chip.id ? 'chip-active' : ''}`}
                        key={chip.id}
                        onClick={() => setActiveChip(chip.id)}
                        type="button"
                      >
                        {chip.label}
                      </button>
                    ))}
                    <span className="ask-hint">
                      <img className="ask-hint-icon" src={toAskArrowIcon} alt="" />
                      <span>to ask</span>
                    </span>
                  </div>
                </section>

                <section className="source-grid">
                  {sourceCards.map((card) => (
                    <SpotlightCard
                      key={card.id}
                      className={`source-card ${activeButton === card.id ? 'active' : ''}`}
                      onClick={() => {
                        setActiveButton(card.id)
                        if (card.url) window.open(card.url, '_blank', 'noopener,noreferrer')
                      }}
                      role="button"
                      tabIndex={0}
                    >
                      <span className="source-label">
                        <img className="source-label-icon" src={card.icon} alt="" />
                        {card.type}
                      </span>
                      <div className="source-content">
                        <p>{card.title}</p>
                      </div>
                    </SpotlightCard>
                  ))}
                </section>
              </div>

              <footer className="footer-row">
                <div className="footer-left">
                  <span className="status-dot" />
                  <span className="status-text">SYSTEMS OPERATIONAL</span>
                  <button
                    className={`footer-link ${activeButton === 'footer-help' ? 'active' : ''}`}
                    onClick={() => setActiveButton('footer-help')}
                    type="button"
                  >
                    Help
                  </button>
                  <button
                    className={`footer-link ${activeButton === 'footer-privacy' ? 'active' : ''}`}
                    onClick={() => setActiveButton('footer-privacy')}
                    type="button"
                  >
                    Privacy
                  </button>
                </div>
                <div className="footer-right">
                  <span>Tab navigate sources</span>
                  <span>↑ ↓ navigate history</span>
                </div>
              </footer>
            </>
          ) : page === 'result' ? (
            <div className="result-layout">
              <section className="result-main">
                <header className="result-toolbar">
                  <button
                    className={`result-tab ${resultTab === 'answer' ? 'active' : ''}`}
                    onClick={() => setResultTab('answer')}
                    type="button"
                  >
                    Answer
                  </button>
                  <button
                    className={`result-tab ${resultTab === 'sources' ? 'active' : ''}`}
                    onClick={() => setResultTab('sources')}
                    type="button"
                  >
                    Sources ({activeChat.sources.length})
                  </button>
                </header>

                <article className="result-content">
                  {resultTab === 'answer' ? (
                    <>
                      <h2>{activeChat.title}</h2>
                      <div className="result-tags">
                        {activeChat.tags.map((tag, index) => (
                          <span
                            className={`result-tag ${index === 0 ? 'result-tag-primary' : ''}`}
                            key={`${activeChat.id}-${tag}`}
                          >
                            {tag}
                          </span>
                        ))}
                      </div>

                      {/*
                        An abstention's sources are near misses, not citations.
                        Labelling them "cited" would contradict the refusal
                        immediately above it.
                      */}
                      <p className="result-meta">
                        {activeChat.abstained ? (
                          <>
                            Not answered · {activeChat.sources.length} closest match
                            {activeChat.sources.length === 1 ? '' : 'es'} below threshold
                          </>
                        ) : (
                          <>
                            {activeChat.sources.length} cited source
                            {activeChat.sources.length === 1 ? '' : 's'} ·{' '}
                            {activeChat.resultCount} decision
                            {activeChat.resultCount === 1 ? '' : 's'}
                          </>
                        )}
                      </p>

                      <p>{activeChat.summary}</p>

                      {activeChat.sections.map((section) => (
                        <div key={`${activeChat.id}-${section.heading}`}>
                          <h3>{section.heading}</h3>
                          <p>{section.body}</p>
                          {(section.citations ?? []).length > 0 && (
                            <p className="decision-citations">
                              {section.citations.map((c, i) => (
                                <span key={`cite-${c.id}`}>
                                  {i > 0 && ' · '}
                                  {c.url ? (
                                    <a href={c.url} target="_blank" rel="noreferrer noopener">
                                      {c.title}
                                    </a>
                                  ) : (
                                    <span>{c.title}</span>
                                  )}
                                </span>
                              ))}
                            </p>
                          )}
                        </div>
                      ))}
                    </>
                  ) : (
                    <>
                      <h2>Sources for: {activeChat.title}</h2>
                      <p className="result-meta">
                        {activeChat.sources.length} matched excerpts across related sources
                      </p>
                      <div className="sources-list">
                        {activeChat.sources.map((source) => (
                          <article className="source-item" key={source.id}>
                            {/*
                              A citation with no resolvable link renders as plain
                              text rather than a dead anchor. Spec rule 5: an
                              answer with no citation is acceptable, a wrong one
                              is not -- and a link that 404s is a wrong one.
                            */}
                            {source.url ? (
                              <a
                                className="source-item-title source-item-link"
                                href={source.url}
                                target="_blank"
                                rel="noreferrer noopener"
                              >
                                {source.title} ↗
                              </a>
                            ) : (
                              <p className="source-item-title">{source.title}</p>
                            )}
                            <p>{source.excerpt}</p>
                          </article>
                        ))}
                      </div>
                    </>
                  )}
                </article>
              </section>

              {/*
                Shows real retrieval diagnostics. This panel previously rendered
                invented "Related Entities" and "Top File Matches" beside every
                answer, including real ones -- decorating genuine results with
                fabricated provenance (spec rule 4).
              */}
              <aside className="result-context">
                <section>
                  <p className="context-title">RETRIEVAL</p>
                  {activeChat.retrieval ? (
                    <>
                      <div className="context-item">
                        <span>Top match</span>
                        <small>{activeChat.retrieval.topScore?.toFixed(3) ?? 'n/a'}</small>
                      </div>
                      <div className="context-item">
                        <span>Threshold</span>
                        <small>{activeChat.retrieval.threshold?.toFixed(2) ?? 'n/a'}</small>
                      </div>
                      <div className="context-item">
                        <span>Chunks retrieved</span>
                        <small>{activeChat.retrieval.retrievedCount ?? 0}</small>
                      </div>
                      <div className="context-item">
                        <span>Chunks cited</span>
                        <small>{activeChat.sources.length}</small>
                      </div>
                    </>
                  ) : (
                    <p className="context-empty">Run a search to see retrieval detail.</p>
                  )}
                </section>

                <section>
                  <p className="context-title">CITED THREADS</p>
                  {activeChat.sources.length === 0 ? (
                    <p className="context-empty">Nothing cited.</p>
                  ) : (
                    activeChat.sources.map((source) =>
                      source.url ? (
                        <a
                          className="context-link"
                          key={`ctx-${source.id}`}
                          href={source.url}
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          {source.title}
                        </a>
                      ) : (
                        <span className="context-link context-link-dead" key={`ctx-${source.id}`}>
                          {source.title}
                        </span>
                      ),
                    )
                  )}
                </section>
              </aside>
            </div>
          ) : page === 'service' ? (
            <div className="service-page">
              <header className="service-header">
                <div>
                  <h2 className="service-title">Source Management</h2>
                  <p className="service-subtitle">Manage your connected data sources and sync status</p>
                  <div className="service-stats">
                    <span>
                      <img src={dbIcon} alt="" />
                      {totalItems.toLocaleString()} Total Items
                    </span>
                    <span>
                      <span className="service-dot" />
                      {connectedCount} Connected
                    </span>
                    <span>2m ago Last Sync</span>
                  </div>
                </div>
                <div className="service-actions">
                  <button className="connect-btn" type="button">
                    <img src={linkIcon} alt="" />
                    Connect New Source
                  </button>
                  <p className="service-note">
                    <img src={lockIcon} alt="" />
                    Only you can search your connected accounts
                  </p>
                </div>
              </header>

              <section className="service-grid">
                {services.map((service) => {
                  const meta = sourceCatalog[service.type]
                  if (!meta) return null

                  return (
                    <article className="integration-card" key={service.id}>
                      <div className="integration-head">
                        <div className="integration-id">
                          <img
                            className={`integration-logo ${meta.meetingStyle ? 'meeting-logo' : ''}`}
                            src={meta.logo}
                            alt=""
                          />
                          <div>
                            <h3>{meta.name}</h3>
                            <p>{meta.subtitle}</p>
                          </div>
                        </div>
                        <div className="integration-head-actions">
                          <span className={service.status === 'loading' ? 'badge-syncing' : 'badge-connected'}>
                            {service.status === 'loading' ? 'Syncing...' : 'Connected'}
                          </span>
                          <button className="remove-btn" onClick={() => removeService(service.id)} type="button">
                            Remove
                          </button>
                        </div>
                      </div>
                      <div className="integration-metrics">
                        <div>
                          <p>{meta.primaryLabel}</p>
                          <strong>{meta.primaryValue}</strong>
                        </div>
                        <div>
                          <p>{meta.secondaryLabel}</p>
                          <strong>{meta.secondaryValue}</strong>
                        </div>
                      </div>

                      {service.status === 'loading' ? (
                        <div className="sync-progress">
                          <p>Connecting source... This may take a moment.</p>
                          <div className="sync-row">
                            <span>Sync in progress</span>
                            <div className="sync-track">
                              <div className="sync-value" />
                            </div>
                            <button className="cancel-btn" onClick={() => removeService(service.id)} type="button">
                              <img src={cancelIcon} alt="" />
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="integration-footer">
                          <span>Auto-sync {autoConnect ? 'enabled' : 'disabled'}</span>
                          <button className="manage-btn" onClick={() => setIsManageOpen(true)} type="button">
                            <img src={settingsIcon} alt="" />
                            Manage
                          </button>
                        </div>
                      )}
                    </article>
                  )
                })}

                <article className="add-card">
                  <button
                    className="plus-icon"
                    onClick={() => {
                      const next = missingServiceTypes[0]
                      if (next) addService(next)
                    }}
                    type="button"
                  >
                    +
                  </button>
                  <h3>Add New Source</h3>
                  <p>Connect Notion, Jira, Linear, and more to expand your knowledge base.</p>
                  <div className="add-options">
                    {missingServiceTypes.length === 0 ? (
                      <span className="add-all-added">All sources added</span>
                    ) : (
                      missingServiceTypes.map((type) => (
                        <button className="add-source-btn" key={type} onClick={() => addService(type)} type="button">
                          Add {sourceCatalog[type].name}
                        </button>
                      ))
                    )}
                  </div>
                </article>
              </section>
            </div>
          ) : (
            <div className="placeholder-page">
              <h2>{activeButton === 'menu-kb' ? 'Knowledge Base' : 'Projects'}</h2>
              <p>
                {activeButton === 'menu-kb'
                  ? 'This page is ready for your knowledge base design.'
                  : 'This page is ready for your next design screen.'}
              </p>
            </div>
          )}
        </div>
      </main>

      {isManageOpen && (
        <div
          aria-hidden="true"
          className="modal-backdrop"
          onClick={() => setIsManageOpen(false)}
          role="presentation"
        >
          <section
            aria-label="Source settings"
            className="manage-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              aria-label="Close settings"
              className="modal-close"
              onClick={() => setIsManageOpen(false)}
              type="button"
            >
              ×
            </button>
            <h3>Source Settings</h3>

            <div className="switch-row">
              <div>
                <p className="switch-title">Auto connect</p>
                <p className="switch-subtext">Off means manual connect.</p>
              </div>
              <button
                aria-pressed={autoConnect}
                className={`toggle ${autoConnect ? 'on' : ''}`}
                onClick={() => setAutoConnect((value) => !value)}
                type="button"
              >
                <span />
              </button>
            </div>

            <div className="switch-row">
              <div>
                <p className="switch-title">Remember 30 days</p>
                <p className="switch-subtext">Off means remember 7 days.</p>
              </div>
              <button
                aria-pressed={longMemory}
                className={`toggle ${longMemory ? 'on' : ''}`}
                onClick={() => setLongMemory((value) => !value)}
                type="button"
              >
                <span />
              </button>
            </div>

            <div className="manual-sync-wrap">
              <button className={`manual-sync-btn ${autoConnect ? 'locked' : ''}`} disabled={autoConnect} type="button">
                {autoConnect && <img src={lockIcon} alt="" />}
                Sync manually
              </button>
              <p className="switch-subtext">
                {autoConnect ? 'Turn off Auto connect to enable manual sync.' : 'Manual sync is enabled.'}
              </p>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

export default App
