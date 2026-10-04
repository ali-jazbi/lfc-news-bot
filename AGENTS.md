# Token-efficient workflow

Keep token usage low without sacrificing correctness.

- At the start of every new task, mention: "AGENTS.md loaded."
- Be concise. Avoid repeating plans, explanations, or previously established facts.
- Inspect only files relevant to the current task.
- Search for relevant symbols/files before opening large files.
- Never scan node_modules, .next, dist, build, coverage, generated files, lockfiles, or large logs unless explicitly necessary.
- Do not read entire large files when a targeted section, search result, or diff is sufficient.
- Limit terminal output. Prefer filtered commands, targeted searches, head/tail, and concise summaries.
- For large logs, JSON, CSV, database output, or command output, first filter or summarize it and inspect only the relevant portion.
- Prefer git diff and changed files over rereading unchanged files.
- Do not repeatedly reopen files already inspected unless they changed or new evidence requires it.
- Run targeted tests first. Run the full test/build only when needed or before final verification.
- Do not explore unrelated parts of the repository.
- When the task is complete, give a short summary of what changed and any important verification result.
