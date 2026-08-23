---
okf_version: "0.1"
---

# lfc-news-bot — universal memory bundle

One mind across every engine you run. This directory is your OKF bundle:
plain markdown, path = identity, links `[title](/path.md)`, frontmatter classifies each node.

## Folders

- `concepts/` — ideas, architectures, methods, rules (`type: Concept`, `EngineRule`, `Identity`, …)
- `entities/` — people, organizations, systems (`type: User`, `Entity`)
- `projects/` — products and initiatives (`type: Project`)
- `inbox/` — raw notes pending curation → promote into the canon above
- `secret/` — sensitive entries (gitignored; included only with `--include-secret`)
- `mirror/` — live-memory mirrors from each engine (gitignored; `--include-mirror`)
- `ledger/` — append-only event log (`events.jsonl`); never a graph concept — docs/event-ledger.md
- `fleet/` — registry of the agent engines working on this bundle (`registry.json`); never a graph concept — docs/fleet.md

Validate your bundle:

```sh
npx samemind query validate
```
