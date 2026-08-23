---
type: Plan
title:
description:
visibility: internal
status: draft                     # draft | agreed | in-progress | done | superseded
agreed_on:                        # ISO date the current status was agreed (YYYY-MM-DD)
tags: [plan]
timestamp:
source:
relations:
  agreed_with: []
  # e.g. agreed_with: /entities/<person>.md
  covers:
  # e.g. covers: /projects/<name>.md   — the initiative this plan is for
  supersedes: []
  # filled only when replacing a prior plan: supersedes: /projects/<old-plan>.md
---

> Copy this file, drop the `_` prefix (→ `projects/<plan-name>.md`), fill it in.
> A Plan is a *coordinated* course of action. Body: ## Stages then ## Risks. When the
> plan changes, write a NEW Plan with `relations.supersedes` and mark this one
> `status: superseded` — Plans are append-only history. See docs/work-discipline.md
> and demo/projects/plan-lumen-sync.md.

# <plan name>

One line: what this plan achieves and who it was agreed with.

## Stages

1. First stage — concrete and verifiable.

## Risks

- Risk, and the mitigation that keeps it from derailing the plan.
