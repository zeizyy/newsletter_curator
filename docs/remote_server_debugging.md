# Remote Server Debugging

This note captures the production-debug workflow that worked during an incident review of a missed newsletter delivery.

## Use The Debug Endpoint First

If the admin server exposes the token-gated debug route, prefer that before SSH:

```bash
curl -sS \
  -H 'Authorization: Bearer YOUR_DEBUG_LOG_TOKEN' \
  'http://YOUR_SERVER:PORT/debug/logs?merged=1&lines=500'
```

Notes:

- `merged=1` reads the current debug log plus rotated siblings like `debug.ndjson.1` and `debug.ndjson.2.gz`.
- `lines` is capped at `500`.
- The response includes `source_paths`, which tells you exactly which files were merged.
- Without `merged=1`, the route only returns the currently configured debug log file.

## Sandbox Caveat

If the same `curl` command works for the operator locally but fails from Codex with a connection error, rerun it outside the sandbox.

In practice:

- a plain sandboxed `curl` can fail with `curl: (7) Failed to connect ...`
- the same request can succeed when run with escalated permissions

For Codex sessions, request an escalated `curl` rather than assuming the server is down.

## Save Then Parse

The merged payload can be large. Save it locally first, then parse it:

```bash
curl -sS \
  -H 'Authorization: Bearer YOUR_DEBUG_LOG_TOKEN' \
  -o /tmp/newsletter_debug_merged.json \
  'http://YOUR_SERVER:PORT/debug/logs?merged=1&lines=500'
```

Then extract only the relevant date and events:

```bash
python3 - <<'PY'
import json
from pathlib import Path

obj = json.loads(Path('/tmp/newsletter_debug_merged.json').read_text())
lines = [json.loads(line) for line in obj["lines"]]

for line in lines:
    ts = str(line.get("ts", ""))
    if not ts.startswith("YYYY-MM-DD"):
        continue
    print(ts, line.get("event"))
PY
```

Focus first on:

- `daily_orchestrator_stage_started`
- `daily_orchestrator_stage_completed`
- `daily_orchestrator_stage_failed`
- `delivery_readiness`
- `delivery_recipients`
- `delivery_started`
- `delivery_send_started`
- `delivery_send_completed`
- `delivery_failed`
- `daily_orchestrator`

## What The Incident Showed

During the investigated missed-delivery incident:

- ingest completed successfully
- source fetch completed successfully
- the newsletter pipeline completed and persisted the daily newsletter
- the failure happened after `delivery_send_started`
- the concrete error was `Broken pipe`

That means the failure was in the outbound email send path, not in story collection, ranking, or newsletter rendering.

## Quick Triage Checklist

1. Check `/health` first to confirm the admin service is reachable.
2. Fetch `/debug/logs?merged=1&lines=500`.
3. Save the payload locally if the response is too large to inspect inline.
4. Filter to the incident date.
5. Confirm whether the run failed in ingest, delivery readiness, or actual send.
6. If `delivery_send_started` exists but `delivery_send_completed` does not, inspect the corresponding `delivery_failed` event.
