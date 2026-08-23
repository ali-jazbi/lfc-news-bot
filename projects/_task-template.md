---
type: Task
title:
description:
visibility: internal
status: backlog                   # backlog | in-progress | done | blocked
blocked_reason:                   # REQUIRED (non-empty) when status is blocked
tags: [task]
timestamp:
source:
relations:
  project:
  # e.g. project: /projects/<name>.md   — the initiative this task belongs to
---

> Copy this file, drop the `_` prefix (→ `projects/<task-name>.md`), fill it in.
> A Task is the ONE discipline type you edit in place — `status` is its current
> state, not history. `status: blocked` requires a non-empty `blocked_reason`
> (what blocks it, what unblocks it). See docs/work-discipline.md and
> demo/projects/task-*.md.

# <task name>

What "done" looks like for this task — verifiable, one or two sentences.
