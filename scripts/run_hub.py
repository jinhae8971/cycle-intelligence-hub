"""Cycle Intelligence Hub — Aggregator Pipeline.

Reads `registry.yaml`, fetches each system's `latest.json`,
extracts its composite score and dimensions, computes summary
stats, writes JSON for the hub dashboard, and sends a unified
Telegram report covering ALL systems at once.

Stateless. Each run is independent. History persisted via
git commits of `data/hub_summary.json` and snapshots.
"""
from __future__ import annotations

import os
import sys
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml


# ══════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = ROOT / "registry.yaml"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LATEST_FILE = DATA_DIR / "hub_summary.json"
HISTORY_FILE = DATA_DIR / "hub_history.json"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
SNAPSHOTS_DIR.mkdir(exist_ok=True)

MAX_HISTORY_DAYS = 730
TIMEOUT = 25


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ══════════════════════════════════════════════════════════════
# Phase classification (mirrors CCI/ASCI logic for consistency)
# ══════════════════════════════════════════════════════════════

# Hub-level meta-phases — generic enough for any cycle system.
# Subsystems use their own labels (Accumulation, Late Bull etc),
# but the hub maps any score onto these standardized buckets.
PHASE_RANGES = [
    (0, 20,  "Capitulation",   "🧊", "#0a4d68"),
    (20, 40, "Recovery",       "🌱", "#3a8891"),
    (40, 60, "Expansion",      "📈", "#f6c945"),
    (60, 80, "Late Bull",      "🔥", "#e76f51"),
    (80, 101,"Euphoria",       "🚨", "#c1121f"),
]


def hub_phase(score: float | None) -> tuple[str, str, str]:
    if score is None:
        return "Unknown", "❓", "#6b7280"
    for lo, hi, name, emoji, color in PHASE_RANGES:
        if lo <= score < hi:
            return name, emoji, color
    return "Euphoria", "🚨", "#c1121f"


# ══════════════════════════════════════════════════════════════
# Robust fetcher with retries
# ══════════════════════════════════════════════════════════════

def robust_get(url: str, retries: int = 3, backoff: float = 1.5) -> dict | None:
    last_err = ""
    for attempt in range(retries):
        try:
            r = requests.get(
                url, timeout=TIMEOUT,
                headers={
                    "User-Agent": "cycle-hub/1.0",
                    "Cache-Control": "no-cache",
                },
            )
            if r.status_code == 200:
                return r.json()
            if 500 <= r.status_code < 600:
                last_err = f"HTTP {r.status_code}"
                time.sleep(backoff * (attempt + 1))
                continue
            print(f"  [err] {r.status_code}: {url}")
            return None
        except Exception as e:
            last_err = str(e)[:80]
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    print(f"  [fail] {url}: {last_err}")
    return None


# ══════════════════════════════════════════════════════════════
# Path resolution (dot-path into nested dict, e.g. "ccs.composite")
# ══════════════════════════════════════════════════════════════

def resolve_path(data: dict, path: str) -> Any:
    """Walk a dot-separated path into a nested dict. Returns None if not found."""
    if not data or not path:
        return None
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


# ══════════════════════════════════════════════════════════════
# System aggregation
# ══════════════════════════════════════════════════════════════

def fetch_system(system: dict) -> dict:
    """Fetch one system's data and extract its score/phase/dimensions.

    Always returns a dict — even on failure — so the hub can show
    that the system is unreachable rather than crashing entirely.
    """
    sid = system["id"]
    print(f"  Fetching {sid:<10} from {system['data_url']}")

    raw = robust_get(system["data_url"])
    now_iso = datetime.now(timezone.utc).isoformat()

    base = {
        "id":            sid,
        "name":          system["name"],
        "asset_class":   system["asset_class"],
        "description":   system.get("description", ""),
        "icon":          system.get("icon", "•"),
        "color":         system.get("color", "#6b7280"),
        "dashboard_url": system["dashboard_url"],
        "axis":          system.get("axis"),
        "fetched_at":    now_iso,
    }

    if raw is None:
        return {**base, "status": "unreachable", "score": None, "phase": "Unknown",
                "phase_emoji": "❓", "phase_color": "#6b7280",
                "dimensions": None, "source_generated_at": None,
                "stale_hours": None, "subsystem_phase": None}

    score = resolve_path(raw, system["score_path"])
    phase = resolve_path(raw, system["phase_path"])
    dimensions = resolve_path(raw, system["dimensions_path"])
    src_gen = raw.get("generated_at")

    # Compute staleness
    stale_hours = None
    if src_gen:
        try:
            src_dt = datetime.fromisoformat(src_gen.replace("Z", "+00:00"))
            stale_hours = (datetime.now(timezone.utc) - src_dt).total_seconds() / 3600
        except Exception:
            pass

    # Apply hub-level phase classification (uniform across systems)
    h_phase_name, h_emoji, h_color = hub_phase(score)

    result = {
        **base,
        "status":              "ok",
        "score":               round(score, 2) if isinstance(score, (int, float)) else None,
        "subsystem_phase":     phase,        # e.g. "Late Bull" from ASCI itself
        "phase":               h_phase_name, # hub-standardized
        "phase_emoji":         h_emoji,
        "phase_color":         h_color,
        "dimensions":          dimensions,
        "source_generated_at": src_gen,
        "stale_hours":         round(stale_hours, 2) if stale_hours is not None else None,
    }

    if score is not None:
        print(f"    → score {score:.1f} ({h_phase_name})  · stale {stale_hours:.1f}h" if stale_hours
              else f"    → score {score:.1f} ({h_phase_name})")
    else:
        print(f"    → no score parsed (path={system['score_path']})")
    return result


# ══════════════════════════════════════════════════════════════
# Cross-system insights
# ══════════════════════════════════════════════════════════════

def compute_insights(systems_data: list[dict]) -> dict:
    """Generate hub-level insights from cross-system comparison."""
    valid = [s for s in systems_data if s.get("score") is not None]
    if not valid:
        return {
            "total_systems": len(systems_data),
            "active_systems": 0,
            "avg_score": None,
            "spread": None,
            "extreme_count": 0,
            "narratives": [],
        }

    scores = [s["score"] for s in valid]
    avg = sum(scores) / len(scores)
    spread = max(scores) - min(scores)

    # Count systems in extreme zones
    extreme = [s for s in valid if s["score"] >= 80 or s["score"] <= 20]

    # Generate narrative observations
    narratives = []

    # Divergence story
    if spread >= 40:
        max_s = max(valid, key=lambda x: x["score"])
        min_s = min(valid, key=lambda x: x["score"])
        narratives.append({
            "type": "divergence",
            "title": "Major cross-asset divergence",
            "detail": (f"{max_s['name']} ({max_s['score']:.0f}, {max_s['phase']}) "
                       f"vs {min_s['name']} ({min_s['score']:.0f}, {min_s['phase']}) — "
                       f"spread {spread:.0f}"),
        })

    # Synchronized euphoria/capitulation
    high_count = sum(1 for s in valid if s["score"] >= 80)
    low_count = sum(1 for s in valid if s["score"] <= 20)
    if high_count >= 2:
        narratives.append({
            "type": "euphoria_sync",
            "title": "🚨 Multiple systems in Euphoria zone",
            "detail": f"{high_count} systems above 80 — synchronized risk-on exhaustion.",
        })
    if low_count >= 2:
        narratives.append({
            "type": "capitulation_sync",
            "title": "🧊 Multiple systems in Capitulation zone",
            "detail": f"{low_count} systems below 20 — broad opportunity window.",
        })

    # Single-system extremes
    for s in valid:
        if s["score"] >= 85:
            narratives.append({
                "type": "system_extreme",
                "title": f"{s['icon']} {s['name']} — euphoria",
                "detail": f"Score {s['score']:.0f} ({s['phase']}). Historical top zone.",
            })
        elif s["score"] <= 15:
            narratives.append({
                "type": "system_extreme",
                "title": f"{s['icon']} {s['name']} — capitulation",
                "detail": f"Score {s['score']:.0f} ({s['phase']}). Historical bottom zone.",
            })

    # Staleness warnings
    for s in valid:
        if s.get("stale_hours") and s["stale_hours"] > 24:
            narratives.append({
                "type": "stale_data",
                "title": f"⏰ {s['name']} data stale",
                "detail": f"Last update {s['stale_hours']:.0f}h ago — pipeline may be down.",
            })

    return {
        "total_systems":  len(systems_data),
        "active_systems": len(valid),
        "avg_score":      round(avg, 2),
        "spread":         round(spread, 2),
        "extreme_count":  len(extreme),
        "narratives":     narratives,
    }


# ══════════════════════════════════════════════════════════════
# History (compact daily series for sparklines)
# ══════════════════════════════════════════════════════════════

def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_history(snapshot: dict) -> list[dict]:
    """Append today's per-system scores. Dedupe by date (keep latest per day)."""
    history = load_history()
    today = snapshot["ts"][:10]
    history = [h for h in history if h.get("ts", "")[:10] != today]
    history.append(snapshot)
    history.sort(key=lambda h: h.get("ts", ""))

    # Trim to MAX_HISTORY_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_DAYS)
    history = [
        h for h in history
        if datetime.fromisoformat(h["ts"].replace("Z", "+00:00")) >= cutoff
    ]
    return history


def save_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(obj, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [saved] {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


# ══════════════════════════════════════════════════════════════
# Telegram Report
# ══════════════════════════════════════════════════════════════

def send_telegram(message: str, token: str, chat_id: str) -> bool:
    if not token or not chat_id:
        print("  [skip] Telegram credentials missing")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, timeout=20)
        r.raise_for_status()
        print(f"  [ok] Telegram sent ({len(message)} chars)")
        return True
    except Exception as e:
        print(f"  [err] Markdown failed: {e}")
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": message[:4000]},
                              timeout=20)
            r.raise_for_status()
            return True
        except Exception as e2:
            print(f"  [err] Plain fallback: {e2}")
            return False


def format_telegram_report(systems: list[dict], insights: dict,
                            hub_url: str = "") -> str:
    now_kst = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=9))
    ).strftime("%Y-%m-%d %H:%M KST")

    lines = [
        "🏛️ *Cycle Intelligence Hub*",
        f"_{now_kst}_",
        "",
    ]

    # Per-system block
    for s in systems:
        if s.get("score") is None:
            lines.append(f"{s['icon']} *{s['name']}*  —  ⚠️ unreachable")
            continue

        score = s["score"]
        bar_len = int(score / 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        lines.append(f"{s['icon']} *{s['name']}*")
        lines.append(f"   `{bar}` *{score:.0f}* {s['phase_emoji']} {s['phase']}")
        if s.get("subsystem_phase") and s["subsystem_phase"] != s["phase"]:
            lines.append(f"   _subsystem: {s['subsystem_phase']}_")
        lines.append("")

    # Hub stats
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Active: {insights['active_systems']}/{insights['total_systems']}  ·  "
                 f"Avg: *{insights['avg_score']:.0f}*  ·  Spread: {insights['spread']:.0f}")
    lines.append("")

    # Narratives (top 3 most important)
    if insights["narratives"]:
        lines.append("*🎯 Cross-System Insights*")
        for n in insights["narratives"][:3]:
            lines.append(f"• {n['title']}")
            lines.append(f"   _{n['detail']}_")
        lines.append("")

    if hub_url:
        lines.append(f"🔗 [Open Hub Dashboard]({hub_url})")
    lines.append("_Hub v1.0 · Aggregating all cycle intelligence systems_")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 64)
    print(f"  Cycle Intelligence Hub  ·  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 64)

    cfg = {
        "telegram_token":   env("TELEGRAM_TOKEN"),
        "telegram_chat_id": env("TELEGRAM_CHAT_ID"),
        "hub_url":          env("HUB_URL"),
    }

    # ── Load registry ──
    print(f"\n📋 Loading registry: {REGISTRY_FILE.relative_to(ROOT)}")
    if not REGISTRY_FILE.exists():
        print(f"❌ Registry not found")
        return 1
    registry = yaml.safe_load(REGISTRY_FILE.read_text(encoding="utf-8"))
    systems = registry.get("systems", [])
    print(f"  {len(systems)} systems registered")

    # ── Fetch all systems ──
    print(f"\n📥 Fetching system data...")
    systems_data = []
    for sys_def in systems:
        try:
            data = fetch_system(sys_def)
            systems_data.append(data)
        except Exception as e:
            print(f"  [err] {sys_def.get('id', 'unknown')}: {e}")
            traceback.print_exc()

    # ── Compute hub insights ──
    print(f"\n⚙️  Computing cross-system insights...")
    insights = compute_insights(systems_data)
    print(f"  Active: {insights['active_systems']}/{insights['total_systems']}  ·  "
          f"Avg: {insights['avg_score']}  ·  Spread: {insights['spread']}")
    print(f"  Narratives: {len(insights['narratives'])}")
    for n in insights["narratives"]:
        print(f"    • {n['title']}")

    # ── Persist ──
    print(f"\n💾 Persisting JSON...")
    now_iso = datetime.now(timezone.utc).isoformat()

    hub_payload = {
        "generated_at": now_iso,
        "version":      "1.0",
        "systems":      systems_data,
        "insights":     insights,
    }
    save_json(LATEST_FILE, hub_payload)

    # Compact history snapshot
    snapshot = {
        "ts": now_iso,
        "systems": {
            s["id"]: {"score": s.get("score"), "phase": s.get("phase")}
            for s in systems_data
        },
        "avg": insights["avg_score"],
        "spread": insights["spread"],
    }
    history = append_history(snapshot)
    save_json(HISTORY_FILE, history)
    print(f"  History size: {len(history)}")

    # Per-day archive
    snap_file = SNAPSHOTS_DIR / f"{now_iso[:10]}.json"
    save_json(snap_file, hub_payload)

    # ── Telegram ──
    print(f"\n📨 Sending Telegram report...")
    report = format_telegram_report(systems_data, insights, cfg["hub_url"])
    sent = send_telegram(report, cfg["telegram_token"], cfg["telegram_chat_id"])

    print("\n" + "=" * 64)
    print(f"  ✅ Hub pipeline complete")
    print(f"  Active systems: {insights['active_systems']}/{insights['total_systems']}")
    print(f"  Telegram sent:  {sent}")
    print("=" * 64)

    # GitHub Actions step summary
    if env("GITHUB_STEP_SUMMARY"):
        with open(env("GITHUB_STEP_SUMMARY"), "a", encoding="utf-8") as f:
            f.write("## Hub Pipeline Summary\n\n")
            f.write(f"- **Active**: {insights['active_systems']}/{insights['total_systems']}\n")
            f.write(f"- **Avg Score**: {insights['avg_score']}\n")
            f.write(f"- **Spread**: {insights['spread']}\n")
            f.write(f"- **Telegram**: {sent}\n\n")
            f.write("### System Status\n\n")
            f.write("| System | Score | Phase | Stale |\n|---|---|---|---|\n")
            for s in systems_data:
                stale = f"{s['stale_hours']:.1f}h" if s.get("stale_hours") else "—"
                score = f"{s['score']:.0f}" if s.get("score") else "—"
                f.write(f"| {s['icon']} {s['name']} | {score} | {s.get('phase','—')} | {stale} |\n")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n❌ FATAL: {e}")
        traceback.print_exc()
        token = env("TELEGRAM_TOKEN")
        chat = env("TELEGRAM_CHAT_ID")
        if token and chat:
            send_telegram(
                f"❌ *Hub pipeline failed*\n\n```\n{str(e)[:500]}\n```",
                token, chat,
            )
        sys.exit(1)
