---
type: Decision
title:
description:
visibility: internal
agreed_on:                       # ISO date the decision was made (YYYY-MM-DD)
tags: [decision]
timestamp:
source:
relations:
  agreed_with: []
  # e.g. agreed_with: /entities/<person>.md
  about:
  # e.g. about: /projects/<name>.md
  supersedes: []
  # filled only when reversing a prior decision: supersedes: /concepts/<old-decision>.md
---

> Copy this file, drop the `_` prefix (→ `concepts/<decision-name>.md`), fill it in.
> A Decision is a point on the timeline — no `status` field. To change a decision,
> write a NEW Decision with `relations.supersedes` pointing at the old one; never
> rewrite the old node. See docs/work-discipline.md and demo/concepts/decision-lumen-local-first.md.

# <decision name>

One line: the decision itself, stated as a position ("we will …", "we will not …").

## Context

Why this call, what alternatives were weighed, what would change it.
