# Demo script — technical interview

A rehearsed ~10-minute walk-through, plus the machine-setup checklist and fallbacks.
The goal of the demo order: show the *system behaviour* (evidence, citations, refusal, audit),
not just "the LLM writes text".

## Demo-machine setup checklist (do this the day before)

- [ ] Clone the repo; `python -m venv .venv`; activate; `pip install -r api/requirements.txt`.
- [ ] Copy `.env.example` to `.env` and set a valid `OPENAI_API_KEY`.
- [ ] **Network is a demo dependency:** verify the room's wifi if possible and prepare a phone
  hotspot as the primary backup — live drafting calls the model API.
- [ ] Database: `docker compose up -d` (start Docker Desktop first), **or** set
  `DATABASE_URL=sqlite:///assist.db` in `.env` if Docker is uncertain on the interview machine.
- [ ] Seed: `cd api && python -m app.ingest` — must end with `Seeded: ... chunks`.
- [ ] Run: `python -m uvicorn app.main:app --port 8000`; open http://localhost:8000; the health
  chip (top right) must be green with `40 docs · 105 chunks`.
- [ ] Run the eval once (`python eval/run_eval.py`) and keep the output in a terminal tab.
- [ ] Run the tests once (`cd api && python -m pytest`) and keep that output too.
- [ ] Take screenshots of a completed draft and a refusal during rehearsal (offline fallback
  evidence), and keep the browser tab from the rehearsal session open if possible.
- [ ] Close other apps enough that the machine is quiet; plug in power.

## The demo beats (~10 min)

1. **Frame it (30 s).** "Agent-assist with governance, not a chatbot: the agent gets evidence and
   a cited draft; weak evidence means no draft; everything is audited."
2. **Happy path (2 min).** Click the *pushTAN delay (EB-1042)* sample → Draft reply. Narrate the
   order: sources render first (hybrid retrieval), then the draft streams. Point at the S1 card:
   keyword rank #1 *and* high semantic score — "the error code pinned it lexically, the paraphrase
   matched semantically; RRF rewards the agreement."
3. **Citations are load-bearing (1 min).** Click a citation chip in the draft — the source card
   highlights. "A draft with no citations, or citing a source I didn't provide, is discarded by a
   deterministic validator, not by hoping the model behaves."
4. **The refusal (2 min).** Click *Out of corpus (gold)* → Draft reply. The stamp lands:
   "This is the most important screen in the product. The system would rather refuse than
   improvise a fee or a deadline. The refusal is logged with its reason."
5. **Audit trail (1 min).** Open the audit strip: drafted and refused rows, reasons, latency,
   token counts. "This row is what a team lead or an auditor sees. In production this carries the
   agent identity via SSO."
6. **Eval + tests (2 min).** Switch to the terminal tabs: 17-case eval (hit@k, draft rate,
   groundedness, refusals) and 18 unit tests. "Quality is measured, not vibed — and the checks
   are deterministic, so any model or parameter change is directly comparable."
7. **Architecture close (1–2 min).** Open `docs/architecture.md`: cloud target diagram, then the
   substitution table. "Same code locally and in Azure; the model call is an endpoint change.
   And for a client with a strict no-egress policy, the gateway is deliberately two methods —
   an in-environment model server is one new class, zero caller changes. The storage layer's
   pgvector/SQLite dual backend demonstrates exactly that adapter pattern live."

## Likely questions, prepared answers

- *Why not LangChain?* — One wire format, ~120 lines, fully inspectable prompt assembly; in FS I
  want to show an auditor the exact request. Frameworks earn their place at orchestration
  complexity this problem doesn't have (ADR-004).
- *Why pgvector and not Pinecone/Weaviate?* — One moving part, data residency, vendor scope
  (DORA), and honest scale math: a support corpus never reaches the size where a dedicated engine
  wins (ADR-002).
- *How does this scale?* — hnsw index in pgvector, reranker after fusion, ingestion as a
  triggered job, horizontal API replicas — in that order, each with a measurable trigger.
- *What about German?* — Corpus is English for the case study; the embedding model and the
  full-text search config are both per-corpus settings; a multilingual embedding model and the
  `german` text-search config are configuration, not architecture.
- *What breaks first?* — The evidence-gate threshold is corpus-dependent; with a bigger, noisier
  corpus I'd calibrate it from the eval set and add the reranker before touching anything else.
- *Could this run without external model calls?* — Yes by design: the gateway interface is two
  methods; an in-environment inference server implements it without touching any caller. That
  build-out is on the roadmap, deliberately not in the case-study scope.

## Fallbacks if something misbehaves live

- Docker dead → flip `DATABASE_URL` to `sqlite:///assist.db`, re-seed, continue (mention the
  fallback as a feature — it is ADR-002's last consequence in action).
- Room wifi dead → phone hotspot (prepared the day before). Model latency high → keep talking
  through the evidence panel; the sources render before any model call completes.
- No connectivity at all → live drafting and search are off (both embed the query); walk the UI
  on the rehearsal screenshots, the audit rows, the recorded eval and test outputs, and do the
  code/architecture walk — the governance story carries without a live model.