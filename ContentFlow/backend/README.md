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

The API listens on `http://127.0.0.1:8000`. Interactive endpoint documentation
is available at `http://127.0.0.1:8000/docs`.

The frontend calls this local API by default. If the API runs at a different
address, copy `frontend\.env.example` to `frontend\.env.local`, set
`NEXT_PUBLIC_CONTENT_FLOW_API_URL` to that address, and restart the frontend.

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
authorization are not connected.

For HTTPS deployment, set `CONTENT_FLOW_COOKIE_SECURE=true` and configure
`CONTENT_FLOW_ALLOWED_ORIGINS` for the exact frontend origin. Before a public
deployment, add email verification, password recovery, abuse/rate limiting,
backups, and a reviewed production hosting configuration. AI generation,
human approval actions, social account OAuth, and publishing are not connected
yet. Do not expose this development service publicly or upload private
institute/student material until production controls are configured.
