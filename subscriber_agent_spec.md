# Subscriber Agent Spec

This file is scoped to the `subscriber-persona-sources` worktree so the inherited repo-wide `agent_*` harness can remain intact.

## Product Goal
Allow each newsletter subscriber to carry their own `persona` and `preferred_sources` so delivery can send a tailored digest instead of applying one global editorial profile to everyone.

## User Value
Operators can keep one ingest pipeline and one delivery command while serving different readers with different angles and source mixes.

## Scope
- Add subscriber-level preference schema in config.
- Resolve recipients into normalized subscriber profiles.
- Group recipients by effective profile so identical profiles share one generated digest.
- Apply subscriber `preferred_sources` as a per-delivery filter on top of the existing global source allowlist.
- Keep current default behavior when no subscriber overrides exist.

## Out Of Scope For This Stream
- Buttondown metadata sync for subscriber preferences.
- Admin UI for editing large subscriber lists.
- Preview personalization.
- Gmail-specific source filtering semantics beyond source-name matching.

## Current Constraints
- Persona is currently global at `config.persona.text`.
- Repository-backed source enable/disable is currently global.
- Preview still targets the generic default audience rather than personalized variants.

## High-Level Technical Design
### Config model
Add top-level `subscribers` entries keyed by email:
- `email`
- optional `persona.text`
- optional `preferred_sources`

Global `persona.text` remains the fallback default.
Recipient membership still comes from the existing delivery inputs in this order:
1. dry-run recipient override
2. Buttondown recipients when `BUTTONDOWN_API_KEY` is set
3. `email.digest_recipients`

`subscribers` only overrides the effective profile for matching resolved recipient emails. It does not add new recipients by itself.

### Recipient resolution
Normalize all resolved recipients into a common subscriber shape:
- `email`
- `persona_text`
- `preferred_sources`
- `profile_key`

Config recipients, dry-run recipients, and Buttondown recipients should all flow through the same normalization path.

### Delivery behavior
- If no subscriber-specific overrides are active, preserve the current single-digest path and cached newsletter reuse.
- If subscriber-specific overrides are active during delivery, group recipients by `profile_key`.
- Generate one digest per group and send it to every recipient in that group.
- Persist the legacy generic digest under audience key `"default"`.
- Persist personalized groups under their `profile_key` so matching groups can reuse cached newsletters without colliding with the generic digest or other personalized audiences.

### Source filtering
Keep global repository source selection as the coarse allowlist, then narrow candidate links by subscriber `preferred_sources` when provided. Matching is exact after trim/lowercase against candidate `source_name`; an empty or missing list means no additional filtering.

## Quality Bar
- Existing non-personalized delivery behavior remains unchanged.
- Persona and preferred-source overrides are deterministic under test.
- Recipients sharing a profile receive the same digest without duplicate generation work.
- Audience-aware persistence keeps `daily_newsletter_id` stable for telemetry and tracked links.
