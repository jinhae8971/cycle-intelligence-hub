"""Cycle Intelligence Hub aggregation pipeline.

The hub reads registry.yaml, fetches each registered subsystem's
latest JSON endpoint, normalizes available scores, writes data files
for GitHub Pages, and optionally sends one Telegram summary.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = ROOT / "registry.yaml"
DATA_DIR = ROOT / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
LATEST_FILE = DATA_DIR / "hub_summary.json"
HISTORY_FILE = DATA_DIR / "hub_history.json"

TIMEOUT_SECONDS = 25
MAX_HISTORY_DAYS = 730


PHASE_RANGES = [
    (0, 20, "Capitulation", "#0a4d68"),
    (20, 40, "Recovery", "#3a8891"),
    (40, 60, "Expansion", "#f6c945"),
    (60, 80, "Late Bull", "#e76f51"),
    (80, 101, "Euphoria", "#c1121f"),
]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def resolve_path(data: Any, path: str | None) -> Any:
    if not path:
        return None
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def first_path(data: dict[str, Any], paths: list[str] | None) -> Any:
    for path in paths or []:
        value = resolve_path(data, path)
        if value not in (None, ""):
            return value
    return None


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def classify_phase(score: float | None) -> tuple[str, str]:
    if score is None:
        return "No score", "#6b7280"
    for lo, hi, name, color in PHASE_RANGES:
        if lo <= score < hi:
            return name, color
    return "Euphoria", "#c1121f"


def parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    candidates = [
        raw,
        raw.replace("Z", "+00:00"),
        raw.replace(" KST", "+09:00"),
    ]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def robust_get_json(url: str, retries: int = 3) -> tuple[dict[str, Any] | None, str | None]:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                timeout=TIMEOUT_SECONDS,
                headers={
                    "User-Agent": "cycle-intelligence-hub/2.0",
                    "Cache-Control": "no-cache",
                },
            )
            if response.status_code == 200:
                return response.json(), None
            last_error = f"HTTP {response.status_code}"
            if response.status_code < 500:
                return None, last_error
        except Exception as exc:
            last_error = str(exc)[:160]
        if attempt < retries:
            time.sleep(1.5 * attempt)
    return None, last_error or "unknown error"


def load_registry() -> list[dict[str, Any]]:
    if not REGISTRY_FILE.exists():
        raise FileNotFoundError(f"Missing {REGISTRY_FILE}")
    registry = yaml.safe_load(REGISTRY_FILE.read_text(encoding="utf-8")) or {}
    systems = registry.get("systems") or []
    if not isinstance(systems, list):
        raise ValueError("registry.yaml must contain a systems list")
    return systems


def fetch_system(system: dict[str, Any]) -> dict[str, Any]:
    system_id = system["id"]
    data_url = system["data_url"]
    print(f"[fetch] {system_id}: {data_url}")

    base = {
        "id": system_id,
        "name": system["name"],
        "asset_class": system.get("asset_class", "Unknown"),
        "description": system.get("description", ""),
        "label": system.get("label", system_id.upper()),
        "color": system.get("color", "#6b7280"),
        "dashboard_url": system.get("dashboard_url", ""),
        "data_url": data_url,
        "axis": system.get("axis"),
        "fetched_at": iso_now(),
    }

    raw, error = robust_get_json(data_url)
    if raw is None:
        print(f"  status=unreachable error={error}")
        phase, phase_color = classify_phase(None)
        return {
            **base,
            "status": "unreachable",
            "error": error,
            "score": None,
            "phase": phase,
            "phase_color": phase_color,
            "subsystem_phase": None,
            "dimensions": None,
            "source_generated_at": None,
            "stale_hours": None,
            "metrics": {},
        }

    score = as_float(resolve_path(raw, system.get("score_path")))
    if score is not None:
        score = max(0.0, min(100.0, score))
    phase, phase_color = classify_phase(score)
    source_generated_at = first_path(
        raw,
        system.get("generated_at_paths")
        or ["generated_at", "generated_at_iso", "timestamp", "updated_at"],
    )
    source_dt = parse_datetime(source_generated_at)
    stale_hours = None
    if source_dt is not None:
        stale_hours = round((now_utc() - source_dt).total_seconds() / 3600, 2)

    metrics = {}
    for label, path in (system.get("metrics") or {}).items():
        metrics[label] = resolve_path(raw, path)

    result = {
        **base,
        "status": "ok",
        "error": None,
        "score": round(score, 2) if score is not None else None,
        "phase": phase,
        "phase_color": phase_color,
        "subsystem_phase": resolve_path(raw, system.get("phase_path")),
        "dimensions": resolve_path(raw, system.get("dimensions_path")),
        "source_generated_at": source_generated_at,
        "stale_hours": stale_hours,
        "metrics": metrics,
    }
    print(f"  status=ok score={result['score']} stale_hours={stale_hours}")
    return result


def compute_insights(systems: list[dict[str, Any]]) -> dict[str, Any]:
    reachable = [s for s in systems if s.get("status") == "ok"]
    scored = [s for s in reachable if s.get("score") is not None]
    scores = [float(s["score"]) for s in scored]

    narratives = []
    if scores:
        avg = sum(scores) / len(scores)
        spread = max(scores) - min(scores)
        if spread >= 40 and len(scored) >= 2:
            high = max(scored, key=lambda item: item["score"])
            low = min(scored, key=lambda item: item["score"])
            narratives.append({
                "type": "divergence",
                "title": "Large cross-system divergence",
                "detail": (
                    f"{high['name']} is at {high['score']:.0f} while "
                    f"{low['name']} is at {low['score']:.0f}; spread is {spread:.0f}."
                ),
            })
        high_count = sum(1 for s in scored if s["score"] >= 80)
        low_count = sum(1 for s in scored if s["score"] <= 20)
        if high_count >= 2:
            narratives.append({
                "type": "euphoria_sync",
                "title": "Multiple systems are overheated",
                "detail": f"{high_count} scored systems are above 80.",
            })
        if low_count >= 2:
            narratives.append({
                "type": "capitulation_sync",
                "title": "Multiple systems are depressed",
                "detail": f"{low_count} scored systems are below 20.",
            })
    else:
        avg = None
        spread = None

    stale = [s for s in reachable if (s.get("stale_hours") or 0) > 24]
    for system in stale[:5]:
        narratives.append({
            "type": "stale_data",
            "title": f"{system['name']} data is stale",
            "detail": f"Last source update was {system['stale_hours']:.0f} hours ago.",
        })

    return {
        "total_systems": len(systems),
        "reachable_systems": len(reachable),
        "scored_systems": len(scored),
        "avg_score": round(avg, 2) if avg is not None else None,
        "spread": round(spread, 2) if spread is not None else None,
        "stale_systems": len(stale),
        "narratives": narratives,
    }


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_history(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    history = load_history()
    current_day = snapshot["ts"][:10]
    history = [item for item in history if item.get("ts", "")[:10] != current_day]
    history.append(snapshot)
    history.sort(key=lambda item: item.get("ts", ""))

    cutoff = now_utc() - timedelta(days=MAX_HISTORY_DAYS)
    trimmed = []
    for item in history:
        item_dt = parse_datetime(item.get("ts"))
        if item_dt is None or item_dt >= cutoff:
            trimmed.append(item)
    return trimmed


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"[save] {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def format_telegram_report(payload: dict[str, Any], hub_url: str) -> str:
    generated = parse_datetime(payload["generated_at"]) or now_utc()
    kst = generated.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    insights = payload["insights"]
    lines = [
        "*Cycle Intelligence Hub*",
        f"_{kst}_",
        "",
        f"Reachable: {insights['reachable_systems']}/{insights['total_systems']}",
        f"Scored: {insights['scored_systems']}/{insights['total_systems']}",
    ]
    if insights["avg_score"] is not None:
        lines.append(f"Average score: *{insights['avg_score']:.0f}*")
    if insights["spread"] is not None:
        lines.append(f"Spread: {insights['spread']:.0f}")
    lines.append("")

    for system in payload["systems"]:
        score = "n/a" if system["score"] is None else f"{system['score']:.0f}"
        lines.append(f"*{system['label']} {system['name']}*: {score} / {system['phase']}")

    if insights["narratives"]:
        lines.append("")
        lines.append("*Insights*")
        for item in insights["narratives"][:4]:
            lines.append(f"- {item['title']}: {item['detail']}")

    if hub_url:
        lines.append("")
        lines.append(f"[Open dashboard]({hub_url})")
    return "\n".join(lines)


def send_telegram(message: str, token: str, chat_id: str) -> bool:
    if not token or not chat_id:
        print("[telegram] skipped: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is missing")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message[:3900],
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        response.raise_for_status()
        print("[telegram] sent")
        return True
    except Exception as exc:
        print(f"[telegram] failed: {exc}")
        return False


def write_step_summary(payload: dict[str, Any], sent: bool) -> None:
    summary_path = env("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    insights = payload["insights"]
    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("## Cycle Intelligence Hub\n\n")
        summary.write(f"- Reachable: {insights['reachable_systems']}/{insights['total_systems']}\n")
        summary.write(f"- Scored: {insights['scored_systems']}/{insights['total_systems']}\n")
        summary.write(f"- Average score: {insights['avg_score']}\n")
        summary.write(f"- Spread: {insights['spread']}\n")
        summary.write(f"- Telegram sent: {sent}\n\n")
        summary.write("| System | Status | Score | Phase | Stale hours |\n")
        summary.write("|---|---:|---:|---|---:|\n")
        for system in payload["systems"]:
            score = "" if system["score"] is None else f"{system['score']:.0f}"
            stale = "" if system["stale_hours"] is None else f"{system['stale_hours']:.1f}"
            summary.write(
                f"| {system['label']} {system['name']} | {system['status']} | "
                f"{score} | {system['phase']} | {stale} |\n"
            )


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(f"Cycle Intelligence Hub started at {iso_now()}")
    print("=" * 72)

    systems = load_registry()
    print(f"[registry] {len(systems)} systems")

    system_payloads = []
    for system in systems:
        try:
            system_payloads.append(fetch_system(system))
        except Exception as exc:
            print(f"[error] {system.get('id', 'unknown')}: {exc}")
            traceback.print_exc()

    insights = compute_insights(system_payloads)
    generated_at = iso_now()
    payload = {
        "generated_at": generated_at,
        "version": "2.0",
        "systems": system_payloads,
        "insights": insights,
    }
    save_json(LATEST_FILE, payload)

    snapshot = {
        "ts": generated_at,
        "systems": {
            item["id"]: {
                "score": item.get("score"),
                "phase": item.get("phase"),
                "status": item.get("status"),
            }
            for item in system_payloads
        },
        "avg": insights["avg_score"],
        "spread": insights["spread"],
    }
    history = append_history(snapshot)
    save_json(HISTORY_FILE, history)
    save_json(SNAPSHOTS_DIR / f"{generated_at[:10]}.json", payload)

    report = format_telegram_report(payload, env("HUB_URL"))
    sent = send_telegram(report, env("TELEGRAM_TOKEN"), env("TELEGRAM_CHAT_ID"))
    write_step_summary(payload, sent)

    print("=" * 72)
    print("Cycle Intelligence Hub complete")
    print(
        f"reachable={insights['reachable_systems']}/{insights['total_systems']} "
        f"scored={insights['scored_systems']} avg={insights['avg_score']}"
    )
    print("=" * 72)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FATAL: {exc}")
        traceback.print_exc()
        token = env("TELEGRAM_TOKEN")
        chat_id = env("TELEGRAM_CHAT_ID")
        if token and chat_id:
            send_telegram(f"*Hub pipeline failed*\n\n```text\n{str(exc)[:500]}\n```", token, chat_id)
        sys.exit(1)
