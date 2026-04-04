# Product Goal
Make Newsletter Curator a self-hosted product with durable subscriber profiles, low-RAM daily operations, and personalization owned by SQLite instead of Buttondown metadata.

# UX
- Keep the existing admin app for operator tasks like source inspection, preview, and server control.
- Add subscriber-facing `/login` and `/settings` pages in the existing Flask app.
- Use passwordless login so the app stores only hashed login or session state, not raw passwords.
- Let users edit `persona_text` and `preferred_sources` on the settings page.
- Render the final delivery email as one flat ranked story list without section headers or footer CTA chrome.

# Technical Design
- Add SQLite-backed user tables for identity, profile data, and login or session state.
- Store `preferred_sources` as a JSON list so the UI can start simple without blocking future expansion.
- Use the database as the source of truth for per-user personalization.
- Keep Buttondown and YAML as migration fallbacks only until DB profiles are populated.
- Keep the daily pipeline pure; service stop and start belongs in the generated deployment wrapper.
- Reuse the existing Flask and repository stack; do not introduce a second web framework.
- Persona text should only affect the final ranking or selection LLM call.
- Increase early discovery recall by raising the initial candidate budget modestly, not by increasing final newsletter size.

# Migration Strategy
- Backfill current recipients into SQLite from the existing config or Buttondown-derived data.
- Roll out auth first, then settings persistence, then delivery reads from the DB, then cleanup.
- Preserve compatibility shims during migration so existing users still get a working digest.
- Do not make the pending evaluation tasks (`T43` through `T46`) prerequisites for this feature wave.

# MCP Tooling
- Add a local, read-only MCP server so agents and automation can inspect stored newsletter stories without going through the admin UI.
- Expose one recent-story tool first and keep the initial scope to the last 24 hours of repository data.
- Do not trigger fresh retrieval, article fetching, enrichment, or summarization at tool-call time.
- Return metadata only, including source fields, anchor text, stored summary fields, and repository timestamps.
- Query the SQLite repository in read-only mode so the MCP server never initializes, resets, or mutates schema state during normal use.
- Keep the initial transport minimal by implementing newline-delimited JSON-RPC over stdio, matching the current MCP stdio transport.
- Add bounded query ergonomics before packaging or client integration so operators and agents can narrow the read-only feed safely.
- Package the server for local discovery by agent tooling after the tool contract is stable.
- Add a Codex-oriented consumption workflow only after the plugin or manifest contract exists.
- This wave is intentionally separate from the pending evaluation tasks (`T43` through `T46`); do not make them prerequisites for the MCP work.
- Add a token-gated, read-only debug log endpoint on the existing Flask/admin server so operators can share bounded production log tails for remote debugging without exposing arbitrary file reads or admin control surfaces.

# Task Map
- `T57` admin-service quiesce and restart wrapper
- `T58` subscriber login and session model
- `T59` subscriber settings page and DB persistence
- `T60` DB-backed delivery personalization plus signup CTA
- `T61` persona and discovery tuning
- `T62` compatibility cleanup and rollout
- `T63` read-only recent-story MCP server vertical slice
- `T64` launch docs and smoke coverage for the MCP server
- `T65` optional query ergonomics for the recent-story MCP tool
- `T66` publish the MCP server for local agent discovery
- `T68` secure read-only debug log endpoint for production troubleshooting
- `T69` flatten final delivery email ranking and remove footer CTA
