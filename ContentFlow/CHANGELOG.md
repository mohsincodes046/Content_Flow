# Changelog

All notable changes to Content Flow. Newest first. Commits are on the `Mohsin` branch.

## Unreleased

### Facebook and Instagram connections
- After Meta sign-in you choose which Pages and Instagram accounts to add;
  nothing is saved until you do. Pages are paginated; Pages your role cannot
  publish to are flagged. Instagram accounts show followers and linked Page.
- Connection status (`active` / `needs_reconnect`), "Check connection",
  reconnect and disconnect. Meta's expired-token errors flag the account.
- Meta deauthorize and data-deletion callbacks (signed requests verified),
  with a deletion status URL; required for Meta App Review.
- Requested permissions trimmed to what the product uses; adds `read_insights`
  (analytics) and `business_management` (Business Manager Pages).
- New Graph client (`app/meta_graph.py`, API v26.0, configurable with
  `META_GRAPH_VERSION`): Facebook text, photo, multi-photo and video posts;
  Instagram image, Reels and carousels with container status polling and the
  daily publishing limit check. Errors never contain request URLs or tokens.

### Workspaces and roles
- Workspaces own all content, schedules and social accounts; users can belong to
  several (agency staff, clients). Roles: owner (exactly one), admin, editor, client.
- Invitations with single-use, 7-day links; invited people join without creating
  their own workspace. Member role changes, removal, leaving, ownership transfer.
- Every request re-checks membership; other workspaces' items return 404.
- Workspace switcher, real Team page, invitation page; clients only see review.
- Migration `0002_workspace_tenancy` (backup-first, verified, rehearsed on a copy
  of the real database). Login no longer requires owning a workspace.

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
