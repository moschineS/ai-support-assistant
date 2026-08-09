import React, { useCallback, useEffect, useRef, useState } from "react";

const SAMPLES = [
  {
    label: "pushTAN delay (EB-1042)",
    text:
      "Hello, since this morning I am not getting approval notifications on my phone when I log in. " +
      "The screen shows code EB-1042. Is my account hacked?",
  },
  {
    label: "Disputed card charge",
    text:
      "There is a charge of 89.90 EUR on my card from a merchant I do not recognize. " +
      "I never bought anything there. How do I get my money back?",
  },
  {
    label: "Out of corpus (gold)",
    text: "What are your current gold bullion prices and can I buy krugerrands at the branch?",
  },
];

/* Minimal SSE parser over fetch streaming — EventSource cannot POST. */
function parseSseBlock(block) {
  let event = "message";
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

function TypeBadge({ type }) {
  return <span className={`badge badge-${type}`}>{type}</span>;
}

function ScoreBar({ label, value }) {
  if (value == null) return null;
  const pct = Math.max(4, Math.min(100, Math.round(value * 100)));
  return (
    <span className="scorebar" title={`${label}: ${value}`}>
      <span className="scorebar-label">{label}</span>
      <span className="scorebar-track">
        <span className="scorebar-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="scorebar-value">{value.toFixed(2)}</span>
    </span>
  );
}

function SourceCard({ src, index, active, onSelect }) {
  const [open, setOpen] = useState(false);
  return (
    <article
      id={`source-${src.label}`}
      className={`source-card ${active ? "active" : ""}`}
      style={{ animationDelay: `${index * 70}ms` }}
      onClick={() => onSelect(src.label)}
    >
      <header className="source-head">
        <span className="source-label">{src.label}</span>
        <TypeBadge type={src.source_type} />
        {src.doc_date && <span className="source-date">{src.doc_date}</span>}
      </header>
      <h3 className="source-title">{src.doc_title}</h3>
      <div className="source-scores">
        <ScoreBar label="sem" value={src.vector_similarity} />
        {src.keyword_rank != null && (
          <span className="kw-chip" title="keyword match rank">
            kw #{src.keyword_rank}
          </span>
        )}
      </div>
      <p className={`source-content ${open ? "open" : ""}`}>{src.content}</p>
      <button
        className="source-toggle"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
      >
        {open ? "collapse" : "read source"}
      </button>
    </article>
  );
}

/* Render the draft with [S#] citations as clickable chips. */
function DraftText({ text, onCite }) {
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <>
      {parts.map((p, i) => {
        const m = p.match(/^\[(S\d+)\]$/);
        if (!m) return <React.Fragment key={i}>{p}</React.Fragment>;
        return (
          <button key={i} className="cite-chip" onClick={() => onCite(m[1])}>
            {m[1]}
          </button>
        );
      })}
    </>
  );
}

function AuditStrip({ entries }) {
  if (!entries.length) return null;
  return (
    <details className="audit">
      <summary>
        Audit trail <span className="audit-count">{entries.length} recent</span>
      </summary>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>outcome</th>
            <th>reason</th>
            <th>ms</th>
            <th>tokens</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className={e.refused ? "refused" : ""}>
              <td>{e.id}</td>
              <td>{e.refused ? "refused" : "drafted"}</td>
              <td>{e.refusal_reason || "—"}</td>
              <td>{e.latency_ms ?? "—"}</td>
              <td>
                {e.prompt_tokens != null
                  ? `${e.prompt_tokens}/${e.completion_tokens}`
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

export default function App() {
  const [message, setMessage] = useState("");
  const [phase, setPhase] = useState("idle"); // idle|working|streaming|done|refused|error
  const [sources, setSources] = useState([]);
  const [draft, setDraft] = useState("");
  const [doneInfo, setDoneInfo] = useState(null);
  const [refusal, setRefusal] = useState(null);
  const [error, setError] = useState(null);
  const [health, setHealth] = useState(null);
  const [audit, setAudit] = useState([]);
  const [activeSource, setActiveSource] = useState(null);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef(null);
  const draftRef = useRef(null);

  const refreshAudit = useCallback(() => {
    fetch("/api/audit?limit=8")
      .then((r) => r.json())
      .then((d) => setAudit(d.entries || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: "down" }));
    refreshAudit();
    return () => abortRef.current?.abort();
  }, [refreshAudit]);

  useEffect(() => {
    if (phase === "streaming") {
      draftRef.current?.scrollTo({ top: draftRef.current.scrollHeight });
    }
  }, [draft, phase]);

  const selectSource = useCallback((label) => {
    setActiveSource(label);
    document
      .getElementById(`source-${label}`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);

  async function submit() {
    if (message.trim().length < 2 || phase === "working" || phase === "streaming")
      return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setPhase("working");
    setSources([]);
    setDraft("");
    setDoneInfo(null);
    setRefusal(null);
    setError(null);
    setActiveSource(null);
    setCopied(false);

    try {
      const res = await fetch("/api/assist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const parsed = parseSseBlock(buf.slice(0, idx));
          buf = buf.slice(idx + 2);
          if (!parsed) continue;
          const { event, data } = parsed;
          if (event === "meta") {
            setSources(data.sources);
            setPhase("streaming");
          } else if (event === "token") {
            setDraft((d) => d + data.t);
          } else if (event === "done") {
            setDraft(data.draft);
            setDoneInfo(data);
            setPhase("done");
            refreshAudit();
          } else if (event === "refusal") {
            setRefusal(data);
            setPhase("refused");
            refreshAudit();
          } else if (event === "error") {
            throw new Error(data.detail);
          }
        }
      }
    } catch (e) {
      if (e.name === "AbortError") return;
      setError(String(e.message || e));
      setPhase("error");
    }
  }

  function stop() {
    abortRef.current?.abort();
    setPhase(draft ? "done" : "idle");
  }

  async function copyDraft() {
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable (http remote) — select manually */
    }
  }

  const busy = phase === "working" || phase === "streaming";

  return (
    <div className="shell">
      <header className="masthead">
        <div className="wordmark">
          <span className="wordmark-bank">Aventra</span>
          <span className="wordmark-app">Support Assist</span>
        </div>
        <div className="health">
          {health ? (
            health.status === "ok" ? (
              <span className="health-chip ok">
                {health.provider} · {health.backend} · {health.docs} docs ·{" "}
                {health.chunks} chunks
              </span>
            ) : (
              <span className="health-chip bad">
                {health.seeded === false ? "not seeded" : "backend degraded"}
              </span>
            )
          ) : (
            <span className="health-chip">…</span>
          )}
        </div>
      </header>

      <main className="workspace">
        <section className="intake">
          <h2 className="panel-title">Customer request</h2>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
            }}
            placeholder="Paste the customer's message here…"
            rows={9}
            disabled={busy}
          />
          <div className="intake-foot">
            <div className="samples">
              {SAMPLES.map((s) => (
                <button
                  key={s.label}
                  className="sample-chip"
                  disabled={busy}
                  onClick={() => setMessage(s.text)}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <div className="actions">
              {busy ? (
                <button className="btn btn-stop" onClick={stop}>
                  Stop
                </button>
              ) : (
                <button
                  className="btn btn-primary"
                  onClick={submit}
                  disabled={message.trim().length < 2}
                >
                  Draft reply
                </button>
              )}
            </div>
          </div>
          <AuditStrip entries={audit} />
        </section>

        <section className="evidence">
          <h2 className="panel-title">
            Evidence
            {sources.length > 0 && (
              <span className="panel-note">
                {sources.length} sources · hybrid retrieval
              </span>
            )}
          </h2>
          {sources.length === 0 ? (
            <p className="empty-note">
              {phase === "working"
                ? "Searching the knowledge base…"
                : "Retrieved sources appear here before the draft is written."}
            </p>
          ) : (
            <div className="source-list">
              {sources.map((src, i) => (
                <SourceCard
                  key={src.id}
                  src={src}
                  index={i}
                  active={activeSource === src.label}
                  onSelect={selectSource}
                />
              ))}
            </div>
          )}
        </section>

        <section className={`draft-sheet phase-${phase}`}>
          <h2 className="panel-title">
            Draft reply
            {doneInfo && (
              <span className="panel-note">
                audit #{doneInfo.audit_id} · {doneInfo.latency_ms} ms
                {doneInfo.usage?.prompt_tokens != null &&
                  ` · ${doneInfo.usage.prompt_tokens}/${doneInfo.usage.completion_tokens} tokens`}
              </span>
            )}
          </h2>

          {phase === "refused" && refusal && (
            <div className="stamp-wrap">
              <div className="stamp">
                NO DRAFT
                <span className="stamp-sub">{refusal.reason}</span>
              </div>
              <p className="refusal-detail">
                {refusal.detail}
                {refusal.audit_id != null && (
                  <span className="refusal-audit"> Logged as audit #{refusal.audit_id}.</span>
                )}
              </p>
            </div>
          )}

          {phase === "error" && <p className="error-note">{error}</p>}

          {(draft || busy) && phase !== "refused" && (
            <div className="draft-body" ref={draftRef}>
              <DraftText text={draft} onCite={selectSource} />
              {phase === "streaming" && <span className="caret" />}
            </div>
          )}

          {phase === "idle" && !draft && (
            <p className="empty-note">
              The grounded draft streams in here — every claim cited, every
              request audited. Weak evidence means no draft, by design.
            </p>
          )}

          {phase === "done" && draft && (
            <footer className="draft-foot">
              <div className="citations">
                {doneInfo?.citations?.map((c) => (
                  <button key={c} className="cite-chip" onClick={() => selectSource(c)}>
                    {c}
                  </button>
                ))}
              </div>
              <button className="btn btn-ghost" onClick={copyDraft}>
                {copied ? "Copied" : "Copy draft"}
              </button>
            </footer>
          )}
        </section>
      </main>

      <footer className="colophon">
        Bank Aventra is fictional; all knowledge-base content is synthetic.
        Drafts are agent assistance, not customer-facing automation — the agent
        reviews and sends.
      </footer>
    </div>
  );
}