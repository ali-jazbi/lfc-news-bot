# Release & Deployment Policy

## Current mode
Manual/local execution during development: run with `python main.py`, optionally `--once --dry-run` for testing without posting live. Semi-automatic publishing (admin approval before public channel) stays on until translation and duplicate-detection quality is proven stable over time — do not flip to a fully automatic publish mode without explicit sign-off (see THREAT_MODEL.md).

## Hosting requirements
- Outbound internet access only (no inbound webhook needed — the bot uses Telegram long-polling).
- A process supervisor that restarts the bot if it crashes.
- Persistent disk if de-duplication history / cooldown state should survive restarts (optional but recommended).
- Environment variables / secrets manager for `.env` values (never commit `.env`).

## Free/low-cost deployment options (trade-offs)
| Option | Cost | Always-on? | Setup effort | Notes |
|---|---|---|---|---|
| **Oracle Cloud "Always Free" VM** | Free forever (requires card to sign up) | Yes, true 24/7 | Medium (Linux VM + systemd service) | Most robust free option; behaves like running on your own PC but hosted; instant button responses. |
| **A spare PC / mini-PC / Raspberry Pi at home, left on** | Free (electricity only) | Yes, as long as it's on and connected | Low | Simplest if you already have hardware; depends on home internet/power uptime. |
| **Fly.io free allowance** | Small free allowance, then paid | Mostly yes | Medium | Free tier has gotten stricter over time; check current limits before relying on it. |
| **Render.com free web service + uptime pinger** | Free | Sleeps after ~15 min idle unless pinged | Medium | Only works well if you add a tiny HTTP health endpoint and an external pinger (e.g. UptimeRobot); adds complexity for a bot that doesn't need HTTP. |
| **GitHub Actions scheduled workflow (`--once` mode)** | Free (generous free minutes) | No — runs briefly every N minutes (e.g. every 5–10 min), then exits | Low | Zero server maintenance; uses the bot's existing `--once` mode. Trade-off: admin approval buttons only get processed the next time the job runs, so there can be a few minutes' delay reacting to button taps. Good if instant button response isn't critical. |
| **PythonAnywhere free tier** | Free | No — free tier doesn't support always-on tasks, only scheduled/daily tasks and web apps | Low | Not well suited to a 60-second polling loop; mainly useful for very infrequent scheduled runs. |

## Recommendation
- If instant admin-button responses matter: use the **Oracle Cloud Always Free VM** (or keep a dedicated machine on 24/7). Run the bot as a systemd service so it restarts automatically on crash or reboot.
- If a few minutes of delay on button responses is acceptable and you want zero server maintenance: use a **GitHub Actions scheduled workflow** calling `python main.py --once`, on a cron schedule (e.g. every 5–10 minutes).
- Whichever option is chosen, store all secrets (`BOT_TOKEN`, `ADMIN_CHAT_ID`, `CHANNEL_ID`, LLM API keys) in that platform's environment variable / secrets feature, never in the repository.

## Rollback
Because publishing is semi-automatic (admin approval required), a bad deploy mainly risks the bot going silent (no drafts reaching the admin group), not spamming the public channel. If a deploy misbehaves, stop/redeploy the process; there is no public-facing rollback needed unless auto-publish mode is enabled in the future.
