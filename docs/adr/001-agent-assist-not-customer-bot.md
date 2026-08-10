# ADR-001: Agent-assist, not a customer-facing bot

**Status:** accepted · 2026-08-09

## Context

The assignment asks for an AI-powered support assistant that helps agents find information,
generate draft responses, and reduce handling time. The obvious build is a chatbot; in a
financial-services context that is also the riskier build.

## Decision

The system is a workspace for the **human agent**: it retrieves evidence, shows it, and drafts a
reply the agent reviews, edits, and sends. Nothing generated ever reaches a customer without a
human in the loop.

## Rationale

- A bank answering customers with an LLM is a regulated-communication and liability problem
  (wrong fee quoted, wrong deadline promised). A draft an employee approves is an efficiency tool.
- The stated goal is *agent* productivity — "help agents find information faster" — which a
  workspace serves directly; handling time drops because search + first draft collapse into one step.
- Errors are recoverable: the agent sees the evidence next to the draft and can check every claim
  via its citation before sending.

## Consequences

- The UI is evidence-first (sources render before the draft streams).
- Refusals are acceptable UX: "no draft, handle manually" is a legitimate outcome, stamped and
  logged, rather than a hallucinated answer.
- A future customer-facing surface would be a separate product decision with its own controls,
  not a config flag on this one.