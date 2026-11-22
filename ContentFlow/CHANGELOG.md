# Changelog

All notable changes to Content Flow. Newest first. Commits are on the `Mohsin` branch.

## Unreleased

### AI content studio
- **AI studio** page (was "AI captions"): Captions, Content ideas, Rewrite, Repurpose, Hashtags, Call to action, Description and Image tools for Instagram, Facebook, LinkedIn and TikTok.
- Captions: tone, short / medium / long-form, 1-3 variations per platform and an optional call to action. Old requests still work.
- New `POST /api/ai/assist` (ideas, rewrite, repurpose, hashtags, call_to_action, description) and `POST /api/ai/image` (Gemini image model, only when `CONTENT_FLOW_AI_IMAGE_MODEL` is set; images are saved to the library through the normal upload).
- Results are editable; **Use in new post** opens the composer with the text, still a draft.
- Usage: the daily text limit is shared by all tools; images have their own `CONTENT_FLOW_AI_IMAGE_DAILY_LIMIT` (default 10). `GET /api/ai/usage` reports both.

### Separate Facebook / Instagram connect, and deleting used media
- Social accounts: three options, **Connect Instagram & Facebook**, **Connect Facebook**, **Connect Instagram**. All use the same Meta sign-in; the picker then offers only the chosen platform's accounts.
- Content library: media can be deleted unless a post that may still publish (in review, approved, scheduled, publishing) uses it. Drafts, rejected, published and failed posts keep their caption, status and links and just lose the file.

### Public customers and Meta App Review
- Connecting Meta no longer fails for a customer with many Pages when Meta refuses to describe one Page: that Page's Instagram lookup is skipped and logged (a token error still stops the connection).
- `docs/META_APP_REVIEW.md`: production URLs, why non-role users cannot connect yet (Advanced Access, App Review, Business Verification), dashboard status table and the data deletion / deauthorize fixes.
- App icon for Meta: `frontend/public/brand/contentflow-app-icon-1024.png` (1024×1024, from the existing logo mark).

### Clear error for a template CLOUDINARY_URL
- A `CLOUDINARY_URL` that still holds template values (`<your_api_key>`) is now rejected by the API with a plain message, and the startup `DEPLOYMENT CONFIG` warnings report it. Before, the browser sent the file to Cloudinary and showed "Invalid api_key <your_api_key>".

### Startup warnings for local settings on a host
- On Render or Koyeb the API logs `DEPLOYMENT CONFIG:` warnings when public URLs or CORS origins still point at localhost or ngrok, when there is no PostgreSQL URL (SQLite would be erased), or when Cloudinary or secure cookies are missing.

### Frontend uses the live Render API on Vercel
- One shared `apiUrl` in `frontend/lib/api.ts`. The three components no longer hard-code `http://localhost:8000`.
- Vercel builds proxy `/api/*` to `https://content-flow-wqzd.onrender.com` by default (override with `CONTENT_FLOW_API_INTERNAL_URL`). The browser calls same-site `/api`, so the SameSite=Lax session cookie keeps working.

### Free-tier production stack (Koyeb + Neon + Cloudinary + Vercel)
- Optional Cloudinary media storage (`CLOUDINARY_URL`): the browser uploads straight to
  Cloudinary with a one-file signed upload chosen by the API, then the API registers it
  from Cloudinary's own record (type, size, dimensions). Instagram receives Cloudinary
  URLs (JPEG ≤ 1440 px via Cloudinary transformation); Facebook gets the bytes. Deleting
  an asset deletes the remote file. Local disk storage is unchanged when unset.
- AI captions: clear messages when the provider's rate limit is hit or the key is
  rejected; Gemini request path tested.
- Gemini: default model is now `gemini-flash-latest` (Google retired `gemini-2.5-flash`
  for new keys). When Gemini answers busy (5xx), retired (404) or times out, the request
  falls back to `GEMINI_FALLBACK_MODELS` (default `gemini-flash-lite-latest`); quota (429)
  and key errors are not retried. Verified live 17 Nov 2026 with a real key: captions in ~13 s.

- Koyeb image: `backend/Dockerfile` (one worker, no disk needed) and
  `docs/DEPLOY_FREE_STACK.md` (Neon, Cloudinary, Koyeb, Vercel, Meta URLs, keep-alive).
- Publisher no longer polls every minute: it sleeps until the next due post or retry,
  wakes as soon as any request changes data, and otherwise checks every
  `CONTENT_FLOW_PUBLISHER_IDLE_SECONDS` (default 30 min), so Neon can scale to zero.
- `CONTENT_FLOW_TRUSTED_PROXY_HOPS`: real client IP behind several proxies
  (Vercel → Koyeb = 2) for login and registration rate limits.
- Live (17 Nov 2026): Instagram carousel + Facebook multi-photo, and Instagram Reel +
  Facebook video, published by the scheduler on the first attempt.

### Facebook + Instagram go-live preparation
- Meta login requests `pages_manage_posts` again; `read_insights` is requested only when
  `META_EXTRA_SCOPES` includes it (Meta rejects the whole login for permissions that are
  not added to the app's use case).
- Verified live (17 Nov 2026): Page "Daily Needs" and Instagram "rajatalal17" connected
  through real OAuth; a scheduled post was published by the background worker to both
  at the scheduled minute (one attempt each, real post IDs and links stored); Instagram
  account and post insights return real values; Facebook insights return no data yet.
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
