# Changelog

All notable changes to Content Flow. Newest first. Commits are on the `Mohsin` branch.

## Unreleased

### Facebook + Instagram go-live preparation
- Privacy Policy, Terms of Service and Data Deletion pages, linked from the site footer.
- Meta App Review package (`docs/META_APP_REVIEW.md`): permissions mapped to code,
  dashboard settings, reviewer steps, recording checklist, owner items.
- Local database migrated to `0005_analytics_cache` after a verified backup;
  background publisher enabled locally.

### TikTok and LinkedIn
- TikTok: Login Kit OAuth, account discovery, direct video posting (upload,
  status polling, published only on PUBLISH_COMPLETE), automatic token refresh.
  Posts are private until TikTok audits the app.
- LinkedIn: OpenID Connect sign-in, text and single-image posts to the member
  profile (Posts API, version 202610, configurable). Company Pages need
  LinkedIn's Community Management API approval.
- Platform rules for both; connect/reconnect buttons; selectable in the editor
  and bulk scheduler.

### Analytics
- Facebook Page (views, viewers, engagements, profile visits, followers) and
  Instagram (views, reach, accounts engaged, interactions, followers) insights
  for the last 7/28/30 days; per-post metrics for posts published with Content
  Flow; publishing activity summary.
- Each metric is requested separately, so a metric Meta has retired shows as
  "Unavailable" with Meta's reason instead of breaking the page or showing 0.
- Results cached for an hour per workspace (migration `0005`), with a refresh.

### Posts, approvals, scheduling and publishing
- New post model: drafts with media, one target per connected account with an
  optional per-platform caption, live platform checks (Instagram JPEG/aspect
  ratio/carousel/caption/hashtag limits, Facebook photo/video rules).
- Client review: send to a reviewer, approve / reject / request changes with
  comments; full history. Editing approved content needs a new approval.
  Clients see only posts sent to them (and their media).
- Scheduling in the viewer's IANA timezone (daylight saving handled), bulk
  scheduling (all-or-nothing), unschedule, Publish now, Retry failed.
- Publisher: Facebook text/photo/multi-photo/video, Instagram image/Reels/
  carousel via signed expiring media links (PNG/WebP converted to JPEG).
  Atomic claims (no double publishing), automatic retries only for errors Meta
  confirms as temporary, interrupted sends never resent, expired tokens flag
  the account. Every attempt recorded.
- Media library is now persistent (list, view, delete; in-use media protected);
  uploads are verified as real images/videos.
- Migration `0004_posts` copies existing scheduled posts into the new model
  and keeps the old table as an archive.
- New screens: Posts, New post (editor), Review queue; Calendar, Overview,
  Bulk schedule and Content library use the new API.

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
