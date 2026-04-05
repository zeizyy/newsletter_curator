# Remote Server Debugging Playbook

Use this playbook for remote investigation of production issues on the curator server, not just missed newsletter deliveries.

## Start With Operator Inputs

Before attempting any remote investigation, ask the operator for:

- server host
- server port
- debug log token

In Codex sessions, prefer an explicit ask-user step before proceeding. If a dedicated ask-user tool is unavailable in the current mode, ask for the values directly in the conversation rather than guessing from old notes or prior commands.

## Use The Debug Endpoint First

Always prefer the token-gated debug endpoint over SSH for remote investigation:

```bash
curl -sS \
  -H 'Authorization: Bearer YOUR_DEBUG_LOG_TOKEN' \
  'http://YOUR_SERVER:PORT/debug/logs?merged=1&lines=500'
```

This should be the default path for:

- delivery failures
- ingest failures
- scheduler or orchestrator failures
- admin-server request failures
- unexpected job timing or missing-stage behavior
- production verification after a fix

If the current debug endpoint does not expose enough information for a read-only investigation, treat that as missing product functionality and prefer implementing the missing debug surface instead of defaulting to SSH.

SSH should be reserved for exceptional cases where:

- the server is not reachable over the exposed admin interface
- the debug endpoint is unavailable because the service is down
- the user explicitly asks for SSH-based investigation

## Debug Endpoint Notes

- `merged=1` reads the current debug log plus rotated siblings like `debug.ndjson.1` and `debug.ndjson.2.gz`.
- `lines` is capped at `500`.
- The response includes `source_paths`, which shows exactly which files were merged.
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

## General Triage Flow

1. Ask the user for the server host, port, and debug token.
2. Check `/health` to confirm the admin service is reachable.
3. Fetch `/debug/logs?merged=1&lines=500`.
4. Save the payload locally if it is too large to inspect inline.
5. Filter to the incident date or suspected failure window.
6. Identify the last successful stage and the first failing or missing stage.
7. Decide whether the failure is in service reachability, ingest, ranking, rendering, persistence, or outbound delivery.
8. If the logs lack a decisive signal, extend the debug endpoint or emitted events before attempting a more invasive remote workflow.

## Useful Event Families

Start with the event names that bracket stage transitions and failures:

- `daily_orchestrator_stage_started`
- `daily_orchestrator_stage_completed`
- `daily_orchestrator_stage_failed`
- `daily_orchestrator`
- `delivery_readiness`
- `delivery_recipients`
- `delivery_started`
- `delivery_send_started`
- `delivery_send_completed`
- `delivery_failed`

Also look for any event names tied to the subsystem under investigation, then correlate them by timestamp.

## Interpreting Results

- If `/health` fails, start with service reachability and deployment state.
- If stage start events are missing entirely, investigate scheduler or invocation problems.
- If ingest stages fail, focus on Gmail, publisher-feed fetch, parsing, and persistence.
- If newsletter generation finishes but delivery does not, focus on recipient resolution and outbound email send.
- If delivery starts but never completes, inspect the corresponding `delivery_failed` event or transport error.
- If the current event stream is insufficient to answer the question, add the missing structured event or read-only debug view and retry through the endpoint.
