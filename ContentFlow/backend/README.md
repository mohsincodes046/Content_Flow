# Content-Flow API

The API receives content submissions and media for the Content-Flow frontend.
It stores submission records in SQLite and uploaded media in a local data folder.

## Run locally on Windows

From the repository root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The backend automatically loads `backend\.env` when the app starts. Variables
already set in the process environment take precedence.

The API listens on `http://127.0.0.1:8000`. Interactive endpoint documentation
is available at `http://127.0.0.1:8000/docs`.

The frontend calls this local API by default. If the API runs at a different
address, copy `frontend\.env.example` to `frontend\.env.local`, set
`NEXT_PUBLIC_CONTENT_FLOW_API_URL` to that address, and restart the frontend.

## AI captions

The authenticated `POST /api/ai/captions` endpoint generates a separate caption
and hashtag list for each selected platform. It supports Claude (default),
OpenAI, and Gemini. Copy `.env.example` to `.env` in this directory, set the key
for the provider you choose, then start the API with:

```powershell
uvicorn app.main:app --env-file .env --reload
```

Keep provider keys only in the backend environment. Never put them in frontend
variables or commit the `.env` file. Without a configured key, the endpoint
returns `503` and the captions page explains that setup is needed.

For Claude, set `CONTENT_FLOW_AI_PROVIDER=claude` and `ANTHROPIC_API_KEY`. For
OpenAI, set `CONTENT_FLOW_AI_PROVIDER=openai` and `OPENAI_API_KEY`. For Gemini,
set `CONTENT_FLOW_AI_PROVIDER=gemini` and `GEMINI_API_KEY`. Model names can be
changed with `CLAUDE_MODEL`, `OPENAI_MODEL`, or `GEMINI_MODEL`.

## Meta account connection

Meta OAuth can connect Facebook Pages and Instagram professional accounts
linked to those Pages. Set `META_APP_ID`, `META_APP_SECRET`, and
`CONTENT_FLOW_TOKEN_ENCRYPTION_KEY` in `backend\.env` (or the backend service
environment), then restart the backend. The encryption key must be a valid
Fernet key; generate one locally with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For local development, expose the backend (`127.0.0.1:8000`) through an HTTPS
tunnel such as ngrok and set `CONTENT_FLOW_API_PUBLIC_URL` to its HTTPS URL. The
frontend can continue using `http://localhost:3000`; Meta redirects to the HTTPS
backend callback, which then returns to the local frontend. Meta OAuth will not
start if the configured callback base URL is plain HTTP.

Register the exact callback URL, including the tunnel host, in the Meta
Developer app's Facebook Login settings under **Valid OAuth Redirect URIs**:

```text
https://YOUR-HTTPS-TUNNEL/api/social/oauth/meta/callback
https://contentflow-api.onrender.com/api/social/oauth/meta/callback
```

For a local ngrok session, replace `YOUR-HTTPS-TUNNEL` with the HTTPS hostname
shown by ngrok. If that hostname changes, update both the backend environment
and Meta's allowed redirect URI, then restart the backend.

For Page and linked Instagram access, configure Facebook Login and request
`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
`instagram_basic`, and `instagram_content_publish`. Meta app review/Advanced
Access may be required for accounts outside the app's roles. Instagram must be a
professional account linked to a Facebook Page. Keep the App Secret and token
encryption key in backend-only environment settings.

The Meta connection endpoints are `GET /api/social/providers`,
`GET /api/social/oauth/meta/start`,
`GET /api/social/oauth/meta/callback`, and
`DELETE /api/social/accounts/{account_id}`. OAuth state is short-lived and
single-use; provider tokens are encrypted at rest and never included in API
responses.

## Render deployment foundation

The repository-root `render.yaml` defines the Next.js web service and FastAPI
web service. Connect the Git repository in Render and create a Blueprint from
that file. The API uses a persistent disk for its current SQLite database and
uploads, so its configured `0.5c-512mb` plan and disk require a paid Render
service. Keep it at one instance; SQLite and local disk are not shared across
instances.

Add `ANTHROPIC_API_KEY` as a secret in Render's API service settings. The
Blueprint currently expects the frontend URL
`https://contentflow-web.onrender.com`; if Render assigns a different frontend
URL, update `CONTENT_FLOW_ALLOWED_ORIGINS` in the API service and redeploy it.
The API URL is passed to the frontend by the Blueprint.

This is deployment configuration only. Social OAuth, platform publishing,
OAuth callback URLs, and the scheduled-post worker still need implementation
before public posts can be connected or sent. Do not register provider callback
URLs until those routes exist.

Set `CONTENT_FLOW_DATA_DIR` to move the SQLite database and uploads out of
`backend\data`. Set `CONTENT_FLOW_ALLOWED_ORIGINS` to a comma-separated list
of frontend origins when running outside the local development defaults.

## Initial endpoints

- `GET /api/health` — check that the API is running.
- `POST /api/auth/register` — create a user and workspace; starts a session.
- `POST /api/auth/login` — start a session with email and password.
- `GET /api/auth/me` — return the signed-in user and workspace.
- `POST /api/auth/change-password` — verify the current password and set a new
  Content-Flow password (8–128 characters); other active sessions are revoked.
- `POST /api/auth/logout` — revoke the current session.
- `GET /api/scheduled-posts` — list the signed-in user's scheduled-post records.
- `POST /api/scheduled-posts` — save a batch of scheduled-post details.
- `PATCH /api/scheduled-posts/{id}` — change a post's scheduled date.
- `DELETE /api/scheduled-posts/{id}` — remove a scheduled post.
- `POST /api/assets` — upload one image or video (up to 50 MB).
- `POST /api/ai/captions` — generate platform-specific captions and hashtags
  with the configured Claude, OpenAI, or Gemini provider.
- `GET /api/social/providers` — show configured Meta OAuth status and the
  signed-in workspace's connected accounts.
- `GET /api/social/oauth/meta/start` and
  `GET /api/social/oauth/meta/callback` — authorize Facebook Pages and linked
  Instagram professional accounts through Meta.
- `DELETE /api/social/accounts/{account_id}` — disconnect one owned account.
- `POST /api/submissions` — save campaign instructions, target audience,
  language, selected platforms, and uploaded asset IDs.
- `GET /api/submissions` — list recent submissions.
- `GET /api/submissions/{id}` — read one submission.

Upload assets first, then send their returned IDs as `asset_ids` when creating
a submission. Accepted platforms are `instagram`, `facebook`, `linkedin`,
`youtube`, and `tiktok`.

New accounts get a private workspace. Passwords are hashed with Argon2, and
signup requires a Content-Flow password of at least 8 characters (separate
from your email password). The authenticated password-change endpoint also
requires the current Content-Flow password and keeps the current session
active. Sessions use random HttpOnly cookies whose tokens are stored hashed,
and submissions/uploads are scoped to the signed-in account. Signup and login
are available to anyone who can reach this local development server.

Scheduled-post records persist their media filename, caption, local date and
time, and selected platforms. The bulk-schedule screen currently saves those
details, not the selected media file itself; publishing and platform
OAuth connection for Meta is implemented but requires a registered Meta app,
credentials, and approved scopes. TikTok, LinkedIn, and YouTube OAuth, publishing
to any platform, and the scheduled-post worker are not implemented. AI captions
require a configured provider key.

For HTTPS deployment, set `CONTENT_FLOW_COOKIE_SECURE=true` and configure
`CONTENT_FLOW_ALLOWED_ORIGINS` for the exact frontend origin. Before a public
deployment, add email verification, password recovery, abuse/rate limiting,
backups, and a reviewed production hosting configuration. Human approval
actions and social publishing are not connected yet. Do not expose this development service publicly or upload private
institute/student material until production controls are configured.
