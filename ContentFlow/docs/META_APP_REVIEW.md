# Meta App Review — submission package

Every statement below describes code that exists in this repository. Do **not** submit
until the "Owner must provide" items are done, and the owner has approved the submission.

**Production (checked 19 Nov 2026)**

| | URL |
|---|---|
| Web app | `https://content-flow-plum-zeta.vercel.app` |
| API (`CONTENT_FLOW_API_PUBLIC_URL`) | `https://content-flow-wqzd.onrender.com` |
| OAuth redirect URI the API sends | `https://content-flow-wqzd.onrender.com/api/social/oauth/meta/callback` |
| Meta app | "Content Flow", ID `1460721630450284`, category Business and pages |

## 0. Why other people cannot connect yet

The code is not the blocker. The owner's own Facebook and Instagram connect and publish,
and production checks with separate customer accounts showed full isolation (another
workspace's media, posts, OAuth connections and social accounts all return 404).

Meta itself limits who may sign in to the app:

- The app has **one role, its administrator** (Graph `/{app-id}/roles`, 19 Nov 2026) and
  no test users. A Business app only grants its permissions to people with a role on the
  app until each permission has **Advanced Access**.
- Advanced Access for the permissions below is granted only through **App Review**, and
  Meta requires **Business Verification** of the business that owns the app first.
- Until then, add each friend or early customer under **App roles → Roles → Add people**
  (role *Tester*); they must accept the invitation at developers.facebook.com. That works
  today, for a limited group, without App Review.

A customer also needs, on their side: a Facebook **Page** they manage (role with
"Create content" or full control), and for Instagram a **Professional** (Business or
Creator) account **linked to that Page**. Personal profiles and unlinked Instagram accounts
cannot be published to by any Meta app.

## 1. Permissions requested (from `backend/app/social_oauth.py` `META_SCOPES`)

`read_insights` is requested only when `META_EXTRA_SCOPES=read_insights` is set, after it
has been added to the app's use case (**Use cases → Customize → Permissions**). Without it,
Page and Facebook post metrics show "Unavailable"; Instagram metrics are unaffected.
Verified 17 Nov 2026: the connected Page token holds `pages_manage_posts` but not
`read_insights`.

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

**Access level needed for public customers:** every permission in the table needs
**Advanced Access** (App Review + Business Verification). Standard Access only covers
people with a role on the app. `read_insights` is optional: leave it out of the first
submission unless Analytics for Facebook Pages must work for customers on day one.

Not requested: `pages_manage_engagement`, `pages_messaging`, `instagram_manage_comments`,
`ads_*`, `email`, `public_profile` beyond the default. Access tokens never reach the browser.

## 2. App settings to configure in the Meta dashboard (owner)

Status from the Graph API and the owner's screenshot, 19 Nov 2026: ✅ done, ❌ to fix.

| Setting | Value | Status |
|---|---|---|
| App domains | `content-flow-wqzd.onrender.com`, `content-flow-plum-zeta.vercel.app` | ✅ |
| Contact email | `zotalalix@gmail.com` | ✅ |
| Privacy Policy URL | `https://content-flow-plum-zeta.vercel.app/privacy` | ✅ |
| Terms of Service URL | `https://content-flow-plum-zeta.vercel.app/terms` | ✅ |
| Category | Business and pages | ✅ |
| User data deletion | Either **Data deletion instructions URL** = `https://content-flow-plum-zeta.vercel.app/data-deletion`, or **Data deletion callback URL** = `https://content-flow-wqzd.onrender.com/api/social/meta/data-deletion`. The callback option currently holds the instructions *page*, which cannot answer Meta's signed POST. Prefer the callback (it deletes the data and returns a status URL and confirmation code). | ❌ |
| App icon | upload `frontend/public/brand/contentflow-app-icon-1024.png` (1024×1024) | ❌ |
| Facebook Login for Business → Settings → Valid OAuth Redirect URIs | `https://content-flow-wqzd.onrender.com/api/social/oauth/meta/callback` | ✅ (owner's connection works) |
| Client OAuth login / Web OAuth login | Yes / Yes | ✅ |
| Deauthorize callback URL (Facebook Login for Business → Settings) | `https://content-flow-wqzd.onrender.com/api/social/meta/deauthorize`; Graph still returns the old ngrok URL | ❌ |
| App roles | add testers for early customers (section 0) | optional |
| Business Verification | Business portfolio of the app → Security Centre → Start verification (legal name, address, phone, documents) | ❌ owner |
| Permissions → Advanced Access | request each permission in section 1 through App Review | ❌ after verification |
| App mode | switch to **Live** after Business Verification and App Review are approved | ❌ |

All URLs are public HTTPS on stable domains, as Meta requires; no tunnels.

## 3. Reviewer instructions (paste into the submission)

> Content Flow is a social media management tool for businesses and agencies. A team
> writes posts, sends them to their client for approval, and publishes approved posts to
> the client's Facebook Page and linked Instagram professional account, now or on a
> schedule, then reviews performance.
>
> 1. Open `https://content-flow-plum-zeta.vercel.app/login` and sign in with the test login: `<test email>` / `<test password>`.
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

- [x] Real support email → `frontend/components/LegalPage.tsx` (`LEGAL_CONTACT.email`): `zotalalix@gmail.com`, live on `/privacy`, `/terms`, `/data-deletion`.
- [x] Public production URLs (see the top of this file).
- [ ] App icon uploaded (file ready in the repo).
- [ ] Data deletion and deauthorize URLs corrected (section 2).
- [ ] Legal entity / business name, address, and Business Verification documents.
- [ ] Data-handling questionnaire answers (data processors, country, retention) — must
      match `/privacy`.
- [ ] A test Facebook user + test Page + linked Instagram professional account for reviewers,
      and a Content Flow test login.
- [ ] The screen recordings (from real accounts — never staged or edited to fake results).
- [ ] Final approval to submit.

## 6. Limitations / risks to know before submitting

- Until approved, only people with a role on the app (admin/developer/tester) can connect.
- `business_management` often triggers extra scrutiny; remove it if not needed.
- Instagram publishing requires media at a public HTTPS URL. In production the media live
  on Cloudinary (`https://res.cloudinary.com/…`), which Instagram fetches directly.
- A customer with many Pages still connects if Meta refuses to describe one of them: that
  Page's Instagram lookup is skipped (logged) instead of failing the whole connection.
- Instagram: no Stories, no product tags, no collaborators. Facebook: no Stories, no Reels
  via the Reels API (videos are posted with `/videos`).
- Metrics Meta does not return for an account/post are shown as "Unavailable", never 0.
