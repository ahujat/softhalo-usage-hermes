"""Writes this adapter's real output for Soft Halo's collector tests.
Usage: python tests/make_fixture.py <output folder>"""

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location("softhalo_usage", Path(__file__).resolve().parents[1] / "__init__.py")
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)

if len(sys.argv) != 2:
    raise SystemExit("usage: python tests/make_fixture.py <output folder>")
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

now = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)
profile = sh.profile_id("/home/u/.hermes")
usage = {"input_tokens": 200, "output_tokens": 80, "cache_read_tokens": 500, "cache_write_tokens": 0, "reasoning_tokens": 20}
cases = {
    "hermes-main.json": sh.build_event("post_api_request", dict(session_id="hm-s1", api_request_id="req-1", provider="anthropic",
                                                                  model="claude-haiku-5-5", ended_at=now.timestamp(), usage=usage), profile, now),
    "hermes-aux.json": sh.build_event("post_auxiliary_call", dict(session_id="hm-s1", aux_task="title", provider="openrouter",
                                                                    model="gpt-5.4-mini", ended_at=now.timestamp(),
                                                                    usage={"input_tokens": 50, "output_tokens": 10}), profile, now),
    "hermes-aux-streaming.json": sh.build_event("post_auxiliary_call", dict(session_id="hm-s1", aux_task="compress", provider="openrouter",
                                                                              model="gpt-5.4-mini", ended_at=now.timestamp(), usage=None), profile, now),
}
for name, record in cases.items():
    record.pop("app_version", None)  # depends on the machine's Hermes install
    (out / name).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(f"wrote {len(cases)} files to {out}")
