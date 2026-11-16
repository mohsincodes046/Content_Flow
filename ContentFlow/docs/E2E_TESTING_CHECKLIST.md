# Content Flow — end-to-end testing checklist

Use real accounts you control. Tick each line; note anything unexpected.

## 0. One-time setup (owner)

- [ ] Back up and migrate the local database: in `backend`, run
      `python -m app.migrate upgrade` (takes a verified backup first). Expect
      "Database is at revision 0005_analytics_cache".
- [ ] `backend/.env`: `META_APP_ID`, `META_APP_SECRET`, `CONTENT_FLOW_TOKEN_ENCRYPTION_KEY`,
      `CONTENT_FLOW_API_PUBLIC_URL` = an **HTTPS** tunnel to the API (needed for Meta
      sign-in and Instagram media), `CONTENT_FLOW_PUBLISHER_ENABLED=true`, and an AI key
      (`ANTHROPIC_API_KEY`).
- [ ] Meta app: add `<API URL>/api/social/oauth/meta/callback` as a Valid OAuth Redirect
      URI; your Facebook user has a role on the app (until App Review).
- [ ] A test Facebook Page, with a linked Instagram **Business/Creator** account.
- [ ] Start: `npm run dev` from the repository's `ContentFlow` folder.

## 1. Accounts and workspaces
- [ ] Register a new account; you land on Overview with real (empty) numbers.
- [ ] Sign out and in again; wrong password 5× locks the email for 15 minutes.
- [ ] Team → invite an editor and a client; open each link in a private window; join.
- [ ] Client sees only Review queue and Settings.
- [ ] Create a second workspace from the switcher; data does not cross workspaces.

## 2. Connect Facebook and Instagram
- [ ] Social accounts → Connect Facebook & Instagram → approve every permission.
- [ ] The picker lists your Pages and the linked Instagram account; choose them; Add.
- [ ] "Check connection" shows Connected.
- [ ] Disconnect one and reconnect it.

## 3. Create content
- [ ] New post: title, caption, "Write with AI" (needs AI key), upload a JPEG and a PNG.
- [ ] Tick the Page and the Instagram account; give Instagram its own caption.
- [ ] Try a very wide image for Instagram → "aspect ratio" warning after saving.
- [ ] Save draft; reopen it from Posts; edit; delete a different draft.
- [ ] Content library lists uploads after a page reload; in-use media can't be deleted.

## 4. Client approval
- [ ] Choose the client as reviewer → Send for review.
- [ ] As the client: Review queue shows the post and images; Request changes with a comment.
- [ ] As the editor: comment visible in History; edit; Send for review again.
- [ ] As the client: Approve. Editing the approved post sends it back to draft.

## 5. Publishing (real posts — use test accounts)
- [ ] Publish now on an approved post → Facebook and Instagram both "Published" with
      "View post" links that open the real posts.
- [ ] Schedule a post 5 minutes ahead; close the browser; it publishes on time.
- [ ] Carousel (2–3 images) to Instagram; multi-photo to Facebook; one MP4 to both.
- [ ] Failure path: revoke the app in Facebook settings, publish → account shows
      "Needs reconnect"; reconnect; "Retry failed" publishes.
- [ ] Bulk schedule a week of posts to the Page; Calendar shows them; drag one to
      another day.

## 6. Analytics
- [ ] Analytics shows Page and Instagram metrics for 7/28 days; unavailable metrics say
      "Unavailable" (not 0); per-post metrics appear for posts published above.

## 7. TikTok and LinkedIn (only if app credentials exist)
- [ ] Connect TikTok; publish an MP4 → appears as a private (Only me) TikTok post.
- [ ] Connect LinkedIn; publish text + image → appears on your profile.
