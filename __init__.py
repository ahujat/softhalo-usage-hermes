"""Soft Halo Usage for Hermes Agent: records token usage for the Soft Halo desktop overlay.

Two observer hooks, ``post_api_request`` (main-loop provider requests) and ``post_auxiliary_call``
(titling, compression and other side calls). Each call writes one softhalo.event/1 file into the
local usage folder. Only allowlisted usage and identity fields are copied; prompts, responses,
messages and tool output in the payload are never read into the record. No network requests.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ADAPTER_VERSION = "0.1.0"
EVENT_MAX_BYTES = 16 * 1024  # Soft Halo refuses event files over 16 KiB
_ID_MAX = 200


# ---------------------------------------------------------------------------------------------
# Folders and identity
# ---------------------------------------------------------------------------------------------

def usage_root(env: dict[str, str], platform: str, home: Optional[str]) -> Optional[Path]:
    """Soft Halo's usage folder on this system, or None when no home folder is known."""
    if platform.startswith("win"):
        local = env.get("LOCALAPPDATA")
        return Path(local) / "Softhalo" / "usage" if local else None
    if not home:
        return None
    if platform == "darwin":
        return Path(home) / "Library" / "Application Support" / "Softhalo" / "usage"
    xdg = env.get("XDG_STATE_HOME", "")
    if xdg.startswith("/"):
        return Path(xdg) / "softhalo" / "usage"
    return Path(home) / ".local" / "state" / "softhalo" / "usage"


# WSL mounts the Windows C: drive here unless /etc/wsl.conf moves it; SOFTHALO_USAGE_DIR covers that case.
WSL_USERS_DIR = "/mnt/c/Users"
_NOT_A_USER = {"all users", "default", "default user", "public"}


def is_wsl(env: dict[str, str], platform: str, os_release: str) -> bool:
    """True inside WSL, where Soft Halo itself runs on the Windows side."""
    return platform.startswith("linux") and bool(
        env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP") or "microsoft" in os_release.lower()
    )


def wsl_usage_root(users_dir: str, linux_user: Optional[str]) -> Optional[Path]:
    """Inside WSL: the Windows user whose ``AppData/Local/Softhalo`` folder exists, seen through the
    drive mount. One such user is the answer; with several, the one named like the Linux user;
    otherwise None, and nothing is written (SOFTHALO_USAGE_DIR then says where)."""
    try:
        people = [
            d.name
            for d in Path(users_dir).iterdir()
            if d.is_dir() and d.name.lower() not in _NOT_A_USER and (d / "AppData" / "Local" / "Softhalo").exists()
        ]
    except OSError:
        return None
    if len(people) == 1:
        pick = people[0]
    else:
        pick = next((p for p in people if linux_user and p.lower() == linux_user.lower()), None)
    return Path(users_dir) / pick / "AppData" / "Local" / "Softhalo" / "usage" if pick else None


def resolve_root(env: dict[str, str], platform: str, home: Optional[str], os_release: str,
                 users_dir: str = WSL_USERS_DIR) -> Optional[Path]:
    """Where to write: SOFTHALO_USAGE_DIR if set, the Windows side inside WSL, else this system's folder."""
    override = env.get("SOFTHALO_USAGE_DIR", "").rstrip("/\\")
    if override:
        return Path(override)
    if is_wsl(env, platform, os_release):
        return wsl_usage_root(users_dir, env.get("USER"))
    return usage_root(env, platform, home)


def hermes_home(env: dict[str, str]) -> str:
    """The active Hermes profile folder (each `hermes -p <name>` profile has its own)."""
    try:
        from hermes_constants import get_hermes_home  # type: ignore

        return str(get_hermes_home())
    except Exception:
        return env.get("HERMES_HOME") or str(Path.home() / ".hermes")


def profile_id(home: str) -> str:
    """One-way id for the Hermes profile folder; the path itself is never written."""
    normalized = home.replace("\\", "/").rstrip("/").lower()
    return "hm-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------

def _counter(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value < 0:  # NaN or negative
        return None
    return int(round(value))


def _clip(value: Any, fallback: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    text = text or fallback
    return text[:_ID_MAX]


def map_usage(usage: Any) -> Optional[dict[str, Optional[int]]]:
    """Hermes's normalised usage onto Soft Halo's four buckets. Hermes already reports uncached
    input separately from cache reads and writes, so nothing is subtracted here."""
    if not isinstance(usage, dict):
        return None
    mapped = {
        "input_uncached": _counter(usage.get("input_tokens")),
        "cache_read": _counter(usage.get("cache_read_tokens")),
        "cache_write": _counter(usage.get("cache_write_tokens")),
        "output": _counter(usage.get("output_tokens")),
        "reasoning": _counter(usage.get("reasoning_tokens")),
    }
    if all(mapped[k] is None for k in ("input_uncached", "cache_read", "cache_write", "output")):
        return None
    return mapped


def _completed_at(value: Any, now: datetime) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    return now


def local_day(at: datetime) -> tuple[str, int]:
    """The local date and UTC offset (minutes) at `at`, by this machine's time zone."""
    local = at.astimezone()
    offset = local.utcoffset() or timedelta(0)
    return local.date().isoformat(), int(offset.total_seconds() // 60)


def build_event(hook: str, payload: dict[str, Any], profile: str, now: datetime) -> dict[str, Any]:
    auxiliary = hook == "post_auxiliary_call"
    if auxiliary:
        call_kind = "auxiliary"
    elif payload.get("parent_session_id"):
        call_kind = "subagent"
    else:
        call_kind = "main"

    status = "failed" if auxiliary and payload.get("error") else "completed"
    completed = _completed_at(payload.get("ended_at"), now)
    day, offset = local_day(completed)

    record: dict[str, Any] = {
        "format": "softhalo.event/1",
        "app": "hermes",
        "adapter_version": ADAPTER_VERSION,
        "profile": profile,
        "session_id": _clip(payload.get("session_id"), "no-session"),
        "call_kind": call_kind,
        "status": status,
        "provider": _clip(payload.get("provider"), "unknown"),
        "model": _clip(payload.get("response_model") or payload.get("model"), "unknown"),
        "completed_at": completed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "utc_offset_minutes": offset,
        "day": day,
        "usage": map_usage(payload.get("usage")),
    }
    version = _hermes_version()
    if version:
        record["app_version"] = version
    parent = payload.get("parent_session_id")
    if isinstance(parent, str) and parent:
        record["parent_session_id"] = _clip(parent, "")
    request_id = payload.get("api_request_id")
    if not auxiliary and isinstance(request_id, str) and request_id:
        # An opaque per-attempt id; unique at least within the session.
        record["request_id"] = _clip(request_id, "")
        record["request_id_scope"] = "session"
    return record


_VERSION: Optional[str] = None


def _hermes_version() -> Optional[str]:
    global _VERSION
    if _VERSION is None:
        try:
            from hermes_cli import __version__  # type: ignore

            _VERSION = str(__version__)
        except Exception:
            _VERSION = ""
    return _VERSION or None


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------

def safe_name(text: str) -> str:
    """File-name-safe form of a session id; the record keeps the real one."""
    cleaned = "".join(c if c.isalnum() and c.isascii() or c in "-_" else "_" for c in text)[:64]
    return cleaned or "unknown"


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_dropped(path: Path) -> int:
    try:
        count = json.loads(path.read_text(encoding="utf-8")).get("count")
        return int(count) if isinstance(count, int) and count > 0 else 0
    except Exception:
        return 0


def publish(root: Path, record: dict[str, Any], now: datetime) -> Optional[Path]:
    """Writes `name.tmp` and renames it into `<root>/inbox/`, so Soft Halo only sees whole files.
    While Soft Halo's `inbox/.full` marker exists nothing is written; the request is counted in
    `hermes-dropped.json` and reported on the next event as `dropped_before`."""
    inbox = root / "inbox"
    dropped_path = root / "hermes-dropped.json"
    inbox.mkdir(parents=True, exist_ok=True)
    dropped = _read_dropped(dropped_path)

    if (inbox / ".full").exists():
        _write_atomic(dropped_path, json.dumps({"count": dropped + 1}))
        return None

    out = dict(record, dropped_before=dropped) if dropped else record
    text = json.dumps(out, separators=(",", ":"))
    if len(text.encode("utf-8")) > EVENT_MAX_BYTES:
        return None
    name = f"hermes-{safe_name(record['session_id'])}-{int(now.timestamp() * 1000)}-{os.getpid()}-{secrets.token_hex(4)}"
    target = inbox / f"{name}.json"
    _write_atomic(target, text)
    if dropped:
        try:
            dropped_path.unlink()
        except FileNotFoundError:
            pass
    return target


# ---------------------------------------------------------------------------------------------
# Hermes entry point
# ---------------------------------------------------------------------------------------------

def _make_hook(hook: str, root: Path, profile: str):
    def on_call(**kwargs: Any) -> None:
        try:
            now = datetime.now(timezone.utc)
            publish(root, build_event(hook, kwargs, profile, now), now)
        except Exception:
            # Usage collection must never disturb the agent: a failed write loses one record only.
            pass

    return on_call


def register(ctx: Any) -> None:
    env = dict(os.environ)
    home = env.get("HOME") or env.get("USERPROFILE") or str(Path.home())
    root = resolve_root(env, sys.platform, home, _platform.release())
    if root is None:
        return
    profile = profile_id(hermes_home(env))
    for hook in ("post_api_request", "post_auxiliary_call"):
        ctx.register_hook(hook, _make_hook(hook, root, profile))
