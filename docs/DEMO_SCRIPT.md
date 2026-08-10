# Demo script — technical interview

A rehearsed ~10-minute walk-through, plus the machine-setup checklist and fallbacks.
The goal of the demo order: show the *system behaviour* (evidence, citations, refusal, audit),
not just "the LLM writes text".

## Demo-machine setup checklist (do this the day before)

- [ ] Clone the repo; `python -m venv .venv`; activate; `pip install -r api/requirements.txt`.
- [ ] Decide the provider for the demo:
  - **Offline (strongest story):** install Ollama; `ollama pull llama3.2:3b` and
    `ollama pull nomic-embed-text`; set `PROVIDER=ollama` in `.env`.
  - **Cloud:** set `PROVIDER=openai` and a valid `OPENAI_API_KEY`; requires internet in the room.
- [ ] Database: `docker compose up -d` (start Docker Desktop first), **or** set
  `DATABASE_URL=sqlite:///assist.db` in `.env` if Docker is uncertain on the interview machine.
- [ ] Seed: `cd api && python -m app.ingest` — must end with `Seeded: ... chunks`.
- [ ] Run: `python -m uvicorn app.main:app --port 8000`; open http://localhost:8000; the health
  chip (top right) must be green with `40 docs · 105 chunks`.
- [ ] Run the eval once (`python eval/run_eval.py`) and keep the output in a terminal tab.
- [ ] Run the tests once (`cd api && python -m pytest`) and keep that output too.
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
   groundedness, refusals) and 18 unit tests. "Quality is measured, not vibed. The checks are
   deterministic, so the same run compares providers."
7. **Architecture close (1–2 min).** Open `docs/architecture.md`: cloud target diagram, then the
   substitution table. "Same code, three fallback substrates — the sovereignty question is a
   config change, and I can show the exact bytes that leave the machine: none, on the Ollama path."

## Likely questions, prepared answers

- *Why not LangChain?* — Two wire formats, ~200 lines, fully inspectable prompt assembly; in FS I
  want to show an auditor the exact request. Frameworks earn their place at orchestration
  complexity this problem doesn't have (ADR-004).
- *Why pgvector and not Pinecone/Weaviate?* — One moving part, data residency, vendor scope
  (DORA), and honest scale math: a support corpus never reaches the size where a dedicated engine
  wins (ADR-002).
- *How does this scale?* — hnsw index in pgvector, reranker after fusion, ingestion as a
  triggered job, horizontal API replicas — in that order, each with a measurable trigger.
- *What about German?* — Corpus is English for the case study; the design point is the embedding
  model choice + `tsvector` config are both per-corpus settings; a multilingual model and
  `german` text-search config are configuration, not architecture.
- *What breaks first?* — The evidence-gate threshold is corpus-dependent; with a bigger, noisier
  corpus I'd calibrate it from the eval set and add the reranker before touching anything else.

## Fallbacks if something misbehaves live

- Ollama slow/dead → flip `.env` to `PROVIDER=openai`, re-seed (~2 min), continue.
- Docker dead → flip `DATABASE_URL` to `sqlite:///assist.db`, re-seed, continue (mention the
  fallback chain as a feature — it is ADR-002's last consequence in action).
- No internet + no Ollama → the seeded SQLite file from rehearsal still serves search; walk the
  UI on retrieval + audit, walk the eval output from the rehearsal tab.