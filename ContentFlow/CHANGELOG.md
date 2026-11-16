# Changelog

All notable changes to Content Flow. Newest first. Commits are on the `Mohsin` branch.

## Unreleased

### Deployment
- `/api` is proxied through the Next.js app (same-origin session cookie) over
  Render's private network; proxied uploads allowed up to 52 MB.
- `render.yaml`: no hard-coded public URLs, correct `rootDir` values relative
  to the repository root, documented Blueprint Path.

### Database
- SQLAlchemy + Alembic; SQLite by default, PostgreSQL via
  `CONTENT_FLOW_DATABASE_URL`. `python -m app.migrate` (backup-first upgrades)
  and `python -m app.transfer` (verified copy between databases). (`55023d7`)

### Earlier Phase 1 work
- Real data and honest empty states instead of demo data in the UI. (`e44e108`)
- Backend split into modules; request IDs and structured logging. (`a6b238f`)
- CI on GitHub Actions: SQLite (Python 3.9, 3.13), PostgreSQL 17, frontend. (`d2c4ed4`, `bfc4bde`)
- Rate limiting and AI caption quotas. (`f00a065`)
- Signed, configurable Meta webhooks. (`468340f`)
- Next.js 16.4.6 security upgrade. (`fac747c`)
- Scheduled Facebook Page image publishing with status in the UI. (`76ead00`, `0d963cf`)
