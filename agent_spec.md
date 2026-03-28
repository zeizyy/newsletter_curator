# Product Goal
Make Newsletter Curator a self-hosted product with durable subscriber profiles, low-RAM daily operations, and personalization owned by SQLite instead of Buttondown metadata.

# UX
- Keep the existing admin app for operator tasks like source inspection, preview, and server control.
- Add subscriber-facing `/login` and `/settings` pages in the existing Flask app.
- Use passwordless login so the app stores only hashed login or session state, not raw passwords.
- Let users edit `persona_text` and `preferred_sources` on the settings page.
- Append a signup CTA to the end of each newsletter email, in both plain text and HTML, pointing to `https://buttondown.com/zeizyynewsletter`.

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

# Task Map
- `T57` admin-service quiesce and restart wrapper
- `T58` subscriber login and session model
- `T59` subscriber settings page and DB persistence
- `T60` DB-backed delivery personalization plus signup CTA
- `T61` persona and discovery tuning
- `T62` compatibility cleanup and rollout
