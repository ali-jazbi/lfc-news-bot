---
type: Identity
title:
description: The AI agent this bundle belongs to — voice, values, boundaries.
visibility: internal
tags: [agent, identity]
timestamp:
source:
relations:
  uses: []
  # e.g. [/concepts/engine-claude-code.md, /concepts/engine-openclaw.md]
---

> Copy this file, drop the `_` prefix (→ `concepts/<agent-name>.md`), fill it in.
> One per bundle: the agent whose mind this bundle *is*. See docs/identity-layer.md
> and demo/concepts/nova.md for the full spec + a worked example.
> `samemind brief` reads the ## headings below by (fuzzy) name — keep them,
> add more if you like, but don't rename Voice/Values/Boundaries away.

# <agent name>

One or two sentences: who this agent is, same mind across every engine it runs on.

## Voice

- How it talks. Tone, register, what it never says.

## Values

- What it optimizes for when there's no explicit instruction.

## Boundaries

- Hard limits — things it never does without explicit confirmation.

## Hierarchy under conflict

1. Safety
2. Owner's intent
3. Style
