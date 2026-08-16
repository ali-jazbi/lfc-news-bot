"""نصب/به‌روزرسانی یکپارچگی Hermes برای News Bot (skills + MCP).

کارها:
  1. کپی hermes_skills/* → HERMES_HOME/skills/
  2. ثبت MCP server (lfc-news) با `hermes mcp add`

اجرا:
    python install_hermes.py          # هر دو مرحله
    python install_hermes.py --mcp-only   # فقط MCP
    python install_hermes.py --skills-only # فقط skills

قابل اجرا روی ویندوز و لینوکس. idempotent است (اجرای مجدد ضرری ندارد).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
SKILLS_SRC = BASE / "hermes_skills"
PROJECT_ROOT = BASE


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes"
    return Path.home() / ".hermes"


def hermes_bin() -> str:
    exe = shutil.which("hermes")
    if exe:
        return exe
    home = hermes_home()
    candidates = [
        home / "hermes-agent" / "venv" / "Scripts" / "hermes.exe",
        home / "hermes-agent" / "venv" / "bin" / "hermes",
        home / "bin" / "hermes",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def install_skills() -> int:
    target = hermes_home() / "skills"
    target.mkdir(parents=True, exist_ok=True)
    n = 0
    for skill_dir in sorted(SKILLS_SRC.iterdir()):
        if not skill_dir.is_dir():
            continue
        dst = target / skill_dir.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(skill_dir, dst)
        n += 1
        print(f"[OK] skill installed: {skill_dir.name}")
    return n


def install_mcp() -> bool:
    exe = hermes_bin()
    if not exe:
        print("[FAIL] hermes binary not found - cannot register MCP")
        return False
    # stdio command: python lfc_mcp_server.py (با مسیر مطلق پروژه)
    py = sys.executable
    server = str(PROJECT_ROOT / "lfc_mcp_server.py")
    cmd = [exe, "mcp", "add", "lfc-news", "--command", py, "--args",
           server, "--connect-timeout", "30"]
    print("running:", " ".join(cmd[:6]) + " ...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                       input="Y\n")
    out = (r.stdout or "").strip() + (r.stderr or "").strip()
    print(out[-600:] if out else "(no output)")
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-only", action="store_true")
    ap.add_argument("--mcp-only", action="store_true")
    args = ap.parse_args()

    print(f"HERMES_HOME: {hermes_home()}")
    print(f"hermes binary: {hermes_bin() or '(not found)'}")

    if not args.mcp_only:
        n = install_skills()
        print(f"{n} skill(s) installed")
    if not args.skills_only:
        ok = install_mcp()
        if not ok:
            print("[WARN] MCP registration had issues - check `hermes mcp list`")


if __name__ == "__main__":
    main()
