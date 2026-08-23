---
type: EngineRule
title: Engine — <engine-id>
description: How <agent name> behaves on the <engine-id> engine — <one-line role>.
visibility: internal
tags: [engine, rule]
timestamp:
source:
engine: <engine-id>
relations:
  part_of: /concepts/<agent-identity>.md
---

> Copy this file to `concepts/engine-<engine-id>.md` (drop the leading `_`,
> name the file after the engine id), fill it in. One per engine the agent
> runs on. `samemind brief --engine <id>` matches by the `engine:` field
> above first, falling back to the `engine-<id>.md` filename convention.
> See docs/identity-layer.md.

# Engine: <engine-id>

One sentence: the role this engine plays (terminal dev / chat orchestrator / batch coder / …).

- Allowed: what it does here.
- Forbidden: what it does not do here (or only with confirmation).
- Style: tone/format specific to this engine.
