# Contributor guidelines

## Release-note gate

- Before every commit or push, use the `release-note-gate` skill from `/Users/lightny/.codex/skills/release-note-gate/SKILL.md`.
- Inspect the staged product outcome across `modral_bot`, `bot-command-center`, and the public `modral` website. State separate in-product and public-update decisions with concrete reasons.
- For a required note, create or update a bilingual database-backed release note in an Alembic migration. Use `scripts/generate_release_note.py` when the product change does not already require its own schema migration.
- Mark an entry public only for a substantial feature, workflow, trust, or availability change worth showing on `modral.app/updates`; small fixes stay in the in-product feed.
- Validate a single Alembic head, offline migration rendering, focused feature and release-note tests, and `git diff --check` before pushing.
- Preserve unrelated work in both repositories and stage only the files or hunks belonging to the requested change.
