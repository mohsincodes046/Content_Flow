# Meta App Review — submission package

Every statement below describes code that exists in this repository. Do **not** submit
until the "Owner must provide" items are done, and the owner has approved the submission.

## 1. Permissions requested (from `backend/app/social_oauth.py` `META_SCOPES`)

| Permission | Where it is used | Justification for reviewers |
|---|---|---|
| `pages_show_list` | `meta_graph.discover_accounts` → `GET /me/accounts` | Lists the Facebook Pages the user manages so they can choose which Pages to connect to their Content Flow workspace. |
| `business_management` | same call, for Pages owned through a Business portfolio | Without it, Pages owned by a Business portfolio are not returned by `/me/accounts`, so agency users cannot connect their clients' Pages. *Drop it if your users only use personally-owned Pages — it is the hardest permission to get approved.* |
| `pages_read_engagement` | Page details, post comment/share counts (`meta_graph.post_insights`) | Shows the connected Page's name and picture, and comment/share counts for posts published through Content Flow. |
| `read_insights` | `meta_graph.account_insights` / `post_insights` (Page metrics `page_media_view`, `page_total_media_view_unique`, `page_post_engagements`, `page_views_total`, and post metrics) | Analytics screen: shows the Page's and each published post's performance to the workspace team. |
| `pages_manage_posts` | `meta_graph.publish_facebook` → `/{page-id}/feed`, `/photos`, `/videos` | Publishes posts that the user wrote and their client approved — immediately or at the time they scheduled. |
| `instagram_basic` | `instagram_business_account{…}` on each Page | Finds the Instagram professional account linked to the Page and shows its username, picture and follower count. |
| `instagram_content_publish` | `meta_graph.publish_instagram` → `/{ig-id}/media` (image, REELS, CAROUSEL), status polling, `/{ig-id}/media_publish` | Publishes approved posts (single image, Reel, carousel) to the user's Instagram professional account. |
| `instagram_manage_insights` | `account_insights` / `post_insights` (`views`, `reach`, `total_interactions`, `likes`, `comments`, `saved`, `shares`) | Analytics screen for the Instagram account and each published post. |

Not requested: `pages_manage_engagement`, `pages_messaging`, `instagram_manage_comments`,
`ads_*`, `email`, `public_profile` beyond the default. Access tokens never reach the browser.

## 2. App settings to configure in the Meta dashboard (owner)

- **App type** Business; product **Facebook Login for Business** (or Facebook Login).
- **Valid OAuth Redirect URI:** `<API public URL>/api/social/oauth/meta/callback`
- **Deauthorize callback URL:** `<API public URL>/api/social/meta/deauthorize`
- **Data deletion request URL:** `<API public URL>/api/social/meta/data-deletion`
  (returns a status URL `…/api/social/meta/data-deletion/{code}` and a confirmation code)
- **Privacy Policy URL:** `<frontend URL>/privacy` · **Terms:** `<frontend URL>/terms` ·
  **User data deletion instructions:** `<frontend URL>/data-deletion`
- App icon (1024×1024), category, **support/contact email** (real, monitored).
- **Business Verification** of the business that owns the app (needed for Advanced Access).
- The URLs must be public HTTPS on a stable domain (the production deployment phase),
  not a temporary tunnel, when the app is submitted.

## 3. Reviewer instructions (paste into the submission)

> Content Flow is a social media management tool for businesses and agencies. A team
> writes posts, sends them to their client for approval, and publishes approved posts to
> the client's Facebook Page and linked Instagram professional account, now or on a
> schedule, then reviews performance.
>
> 1. Open `<frontend URL>` and sign in with the test login: `<test email>` / `<test password>`.
> 2. Go to **Social accounts → Connect Facebook & Instagram**. Log in with the Facebook
>    test user provided and grant the requested permissions.
> 3. Choose the Page "`<test page>`" and its Instagram account "`<test ig>`", click **Add**.
>    Both show **Connected** (`pages_show_list`, `business_management`, `instagram_basic`).
> 4. **New post** → write a caption, upload an image, tick the Page and the Instagram account
>    → **Save** → **Publish now** (the test workspace owner can publish directly).
>    The post appears on the Page and on Instagram; **View post** opens it
>    (`pages_manage_posts`, `instagram_content_publish`).
> 5. **Analytics** shows the Page's and Instagram account's metrics and the post's metrics
>    (`read_insights`, `pages_read_engagement`, `instagram_manage_insights`).
> 6. **Social accounts → Disconnect** removes the account and deletes its stored tokens.

## 4. Screen recording checklist (one video per permission group is fine)

- [ ] Starts logged out; shows signing in to Content Flow.
- [ ] Full Facebook Login dialog including the permission screen, with the app name visible.
- [ ] Page and Instagram account selection, then the Connected state.
- [ ] Creating a post with an image; Publish now; the "Published" status.
- [ ] The live post opened on Facebook and on Instagram (via **View post**).
- [ ] Scheduling a post and it later showing "Published" (optional but helpful).
- [ ] Analytics screen showing the Page, Instagram and per-post numbers.
- [ ] Disconnect.
- [ ] English UI, readable resolution, no secrets on screen (no `.env`, no tokens).

## 5. Owner must provide / confirm (Claude cannot do these)

- [ ] Real support email → `frontend/components/LegalPage.tsx` (`LEGAL_CONTACT.email`).
- [ ] Legal entity / business name, address, and Business Verification documents.
- [ ] Data-handling questionnaire answers (data processors, country, retention) — must
      match `/privacy`.
- [ ] A test Facebook user + test Page + linked Instagram professional account for reviewers,
      and a Content Flow test login.
- [ ] The screen recordings (from real accounts — never staged or edited to fake results).
- [ ] Public production URLs (next phase: deployment).
- [ ] Final approval to submit.

## 6. Limitations / risks to know before submitting

- Until approved, only people with a role on the app (admin/developer/tester) can connect.
- `business_management` often triggers extra scrutiny; remove it if not needed.
- Instagram publishing requires media at a public HTTPS URL. Content Flow serves signed,
  expiring media URLs from the API, so the API must be publicly reachable.
- Instagram: no Stories, no product tags, no collaborators. Facebook: no Stories, no Reels
  via the Reels API (videos are posted with `/videos`).
- Metrics Meta does not return for an account/post are shown as "Unavailable", never 0.
