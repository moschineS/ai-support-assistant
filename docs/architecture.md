# Architecture

Two views of the same system: the **cloud target** the solution is designed for, and the **local
demo topology** it runs as on a laptop. The application code is identical in both — the
environments differ only in configuration (see the substitution table).

## Cloud target (Azure)

```mermaid
flowchart LR
    subgraph client [Support agent]
        B[Browser SPA]
    end

    subgraph azure [Azure subscription]
        ENTRA[Entra ID\nOIDC sign-in]
        subgraph aca [Container Apps environment]
            API[assist-api container\nFastAPI + SPA static]
            JOB[ingestion job\npython -m app.ingest\non document change / schedule]
        end
        AOAI[Azure OpenAI\nchat + embeddings]
        PG[(PG Flexible Server\npgvector: chunks, meta,\naudit_log)]
        BLOB[(Blob Storage\nraw documents)]
        KV[Key Vault\nAPI keys, DB creds]
        MON[Azure Monitor\nmetrics + alerts]
    end

    B -->|HTTPS| ENTRA --> API
    API -->|embed query + draft| AOAI
    API -->|hybrid search + audit| PG
    JOB -->|read documents| BLOB
    JOB -->|chunk + embed| AOAI
    JOB -->|upsert vectors| PG
    KV -.-> API
    KV -.-> JOB
    API -.->|structured logs, cost-aware sampling| MON
```

Notes an operator cares about:

- **One writable store.** Vectors, metadata, and the audit log live in the same Postgres — one
  backup story, one transaction boundary, no vector-DB vendor to onboard (ADR-002).
- **Ingestion is a job, not an endpoint.** Locally it is a CLI (`python -m app.ingest`); in the
  target it runs as a Container Apps job triggered by document changes. The API surface stays
  read-only towards the corpus by construction — there is deliberately no ingestion route.
- **Data residency.** All data-bearing services are region-pinned PaaS. With Azure OpenAI, prompts
  and completions are not used for training; for stricter regimes the gateway interface (two
  methods: embed, chat_stream) accommodates an in-environment model server with no caller changes.
- **Log costs.** Structured logs with sampling and a monthly budget alert — log ingestion is the
  classic silent cost driver in this stack.

## Local demo topology

```mermaid
flowchart LR
    subgraph laptop [Laptop]
        B2[Browser\nlocalhost:8000]
        API2[uvicorn\nFastAPI + SPA static]
        PG2[(pgvector container\nhost port 5433)]
        SQL[(assist.db\nSQLite + FTS5 fallback)]
        CORPUS[corpus/ *.md]
    end
    OAI[OpenAI API\nchat + embeddings]

    B2 --> API2
    API2 -->|HTTPS| OAI
    API2 -->|postgresql://| PG2
    API2 -.->|sqlite:/// fallback| SQL
    CORPUS -->|python -m app.ingest| API2
```

### Component substitution table

| Concern | Local demo | Azure target | Switched by |
|---|---|---|---|
| Compute | `uvicorn` process | Container Apps | deployment |
| Chat + embeddings | OpenAI API | Azure OpenAI | endpoint + credentials |
| Vector + keyword store | pgvector container or SQLite | PG Flexible Server + pgvector | `DATABASE_URL` |
| Raw documents | `corpus/` folder | Blob Storage | ingestion job source |
| Auth | none (localhost) | Entra ID (OIDC) | reverse-proxy / middleware |
| Secrets | `.env` | Key Vault | environment |

The **storage fallback is the resilience story**: with Docker the demo runs on pgvector; without
Docker it falls back to SQLite + FTS5 behind the same store interface. Same code, same ranking
semantics, verified by the same tests — and the same adapter pattern is how an in-environment
model server would slot in behind the gateway for strict no-egress policies.

## Request flow (assist)

```mermaid
sequenceDiagram
    participant A as Agent (SPA)
    participant R as FastAPI /api/assist
    participant G as Gateway (OpenAI)
    participant S as Store (pgvector/SQLite)

    A->>R: POST customer message (SSE)
    R->>S: seed/embedding-model compatibility check
    R->>G: embed(query)
    R->>S: vector_ranked + keyword_ranked
    R->>R: RRF fusion + evidence gate
    alt weak evidence
        R->>S: audit(refused: weak_evidence)
        R-->>A: meta + refusal (no LLM call)
    else evidence sufficient
        R-->>A: meta (sources first)
        R->>G: chat_stream(system, sources+message)
        G-->>A: token stream (relayed)
        R->>R: validate citations / coverage-gap
        alt draft valid
            R->>S: audit(drafted)
            R-->>A: done (draft, citations, usage)
        else invalid
            R->>S: audit(refused + discarded draft)
            R-->>A: refusal
        end
    end
```

## SSE contract

`POST /api/assist` responds `text/event-stream`:

| Event | Payload | Meaning |
|---|---|---|
| `meta` | `{sources, weak}` | Retrieved evidence, sent before any generation |
| `token` | `{t}` | Draft text increment |
| `done` | `{audit_id, draft, citations, usage, latency_ms}` | Validated draft |
| `refusal` | `{reason, detail, audit_id}` | No draft: `weak_evidence`, `model_reported_gap`, `draft_missing_citations`, `draft_citation_invalid`, `retrieval_unavailable`, `gateway_unavailable`, `gateway_error` |
| `error` | `{detail}` | Infrastructure failure mid-stream |

## Data model

```
meta       key -> value(jsonb)      seeded (provider, model, dim, counts)
chunks     id, doc_id, doc_title, source_type, product, doc_date,
           chunk_index, content, embedding vector(dim), tsv (generated)
audit_log  id, ts, request_text, retrieved(jsonb), draft, refused,
           refusal_reason, provider, chat_model, latency_ms,
           prompt_tokens, completion_tokens
```

The `chunks` table is recreated on every seed (the corpus is the source of truth; the table is
derived state) with the embedding dimension of the active embedding model. Exact nearest-neighbour scan
is intentional at demo scale; an `hnsw` index is the documented next step once the corpus grows
(ADR-002).