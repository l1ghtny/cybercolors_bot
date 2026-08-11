# Contributor guidelines

## Release-note gate

- Before every commit or push, use the `release-note-gate` skill from `/Users/lightny/.codex/skills/release-note-gate/SKILL.md`.
- Inspect the staged product outcome across both `modral_bot` and `bot-command-center`, then state `Release note: required` or `Release note: not required` with a concrete reason.
- For a required note, create or update a bilingual database-backed release note in an Alembic migration. Use `scripts/generate_release_note.py` when the product change does not already require its own schema migration.
- Validate a single Alembic head, offline migration rendering, focused feature and release-note tests, and `git diff --check` before pushing.
- Preserve unrelated work in both repositories and stage only the files or hunks belonging to the requested change.
