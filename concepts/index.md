---
okf_version: "0.1"
---

# Concepts

Ideas, architectures, methods, rules. Typical `type` values: `Concept`, `EngineRule`,
`Identity`, `Reference`, `Decision`, `Session`. Start from [`_template.md`](_template.md).

Identity layer (docs/identity-layer.md): [`_identity-template.md`](_identity-template.md) —
the agent's own mind (one per bundle); [`_engine-rule-template.md`](_engine-rule-template.md) —
per-engine role/allowed/forbidden (one per engine). Assemble a compact brief from them:
`npx samemind brief`.

Work discipline (docs/work-discipline.md): [`_decision-template.md`](_decision-template.md) —
a decision and its context (append-only); [`_session-template.md`](_session-template.md) —
a session summary (`## Done` / `## Decided` / `## Next`).

Knowledge cycle (docs/knowledge-cycle.md): [`_analysis-template.md`](_analysis-template.md) —
a conclusion from observed facts (`relations.informs` → an Idea);
[`_research-template.md`](_research-template.md) — a deeper dig (`spawned_by` an
Analysis, `informs` → an Idea); [`_idea-template.md`](_idea-template.md) — a
candidate (`spark → incubating → adopted/rejected`, `## Reflections` from agents).

List concepts: `npx samemind query list`
