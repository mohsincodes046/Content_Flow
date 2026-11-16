"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import {
  api, assetUrl, browserTimezone, canEditContent, formatWhen, statusLabels, toLocalInput,
  type Asset, type Post, type SessionUser,
} from "../lib/api";
import type { SocialAccount } from "./AccountsSection";

type Member = { user_id: string; full_name: string; role: string };
type Draft = {
  title: string; caption: string; assetIds: string[];
  targets: Record<string, { override: string; custom: boolean }>;
  when: string; reviewer: string;
};

const platformName: Record<string, string> = { facebook: "Facebook", instagram: "Instagram" };
const captionLimit: Record<string, number> = { facebook: 63206, instagram: 2200 };
const eventLabel: Record<string, string> = {
  created: "Created", edited: "Edited", submitted: "Sent for review", approved: "Approved", rejected: "Rejected",
  changes_requested: "Changes requested", comment: "Comment", scheduled: "Scheduled", unscheduled: "Unscheduled",
  publish_requested: "Publish now requested", published: "Published", failed: "Failed", retry_scheduled: "Will retry",
  retried: "Retry requested", imported: "Imported",
};

function MediaThumb({ asset, size = 72 }: { asset: Asset; size?: number }) {
  const style = { width: size, height: size };
  return asset.media_type.startsWith("video/")
    ? <video className="compose-thumb" style={style} src={assetUrl(asset.id)} muted aria-label={asset.filename} />
    // Authenticated API media: a plain <img> keeps the session cookie and needs no image-host config.
    // eslint-disable-next-line @next/next/no-img-element
    : <img className="compose-thumb" style={style} src={assetUrl(asset.id)} alt={asset.filename} />;
}

function toDraft(post: Post | null): Draft {
  if (!post) return { title: "", caption: "", assetIds: [], targets: {}, when: "", reviewer: "" };
  return {
    title: post.title, caption: post.caption, assetIds: post.media.map((m) => m.id),
    targets: Object.fromEntries(post.targets.filter((t) => t.social_account_id).map((t) => [
      t.social_account_id as string, { override: t.caption_override ?? "", custom: t.caption_override !== null },
    ])),
    when: toLocalInput(post.scheduled_at), reviewer: post.reviewer_user_id ?? "",
  };
}

export default function ComposePost({ user, setNotice }: { user: SessionUser; setNotice: (value: string) => void }) {
  const router = useRouter();
  const postId = useSearchParams().get("id");
  const [post, setPost] = useState<Post | null>(null);
  const [draft, setDraft] = useState<Draft>(toDraft(null));
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [library, setLibrary] = useState<Asset[]>([]);
  const [reviewers, setReviewers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(Boolean(postId));
  const [busy, setBusy] = useState("");
  const [showLibrary, setShowLibrary] = useState(false);
  const [aiAudience, setAiAudience] = useState("");
  const [comment, setComment] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const editable = canEditContent(user.role);

  useEffect(() => {
    let active = true;
    Promise.all([
      api<{ provider: string; accounts: SocialAccount[] }[]>("/api/social/providers"),
      api<Asset[]>("/api/assets"),
      api<Member[]>("/api/workspaces/current/members"),
      postId ? api<Post>(`/api/posts/${encodeURIComponent(postId)}`) : Promise.resolve(null),
    ]).then(([providers, assets, members, loaded]) => {
      if (!active) return;
      setAccounts(providers.flatMap((p) => p.accounts).filter((a) => a.platform === "facebook" || a.platform === "instagram"));
      // Keep anything uploaded while this request was in flight.
      setLibrary((current) => [...current, ...assets.filter((asset) => !current.some((item) => item.id === asset.id))]);
      setReviewers(members.filter((m) => ["client", "admin", "owner"].includes(m.role) && m.user_id !== user.id));
      // A new post is editable while this loads; never overwrite what was already typed.
      if (loaded) {
        setPost(loaded);
        setDraft(toDraft(loaded));
      }
    }).catch((failure: unknown) => {
      if (active) setNotice(failure instanceof Error ? failure.message : "Unable to load the post.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [postId, user.id, setNotice]);

  const selectedAssets = useMemo(() => draft.assetIds.map((id) => library.find((a) => a.id === id) ?? post?.media.find((m) => m.id === id)).filter((a): a is Asset => Boolean(a)), [draft.assetIds, library, post]);
  const selectedAccounts = accounts.filter((a) => draft.targets[a.id]);
  const status = post?.status ?? "draft";
  const locked = ["publishing", "published", "partially_published"].includes(status);
  const hasReviewer = Boolean(post?.reviewer_user_id);
  const canScheduleNow = !hasReviewer || ["approved", "scheduled", "failed"].includes(status);

  const payload = () => ({
    title: draft.title, caption: draft.caption, asset_ids: draft.assetIds,
    targets: selectedAccounts.map((a) => ({ social_account_id: a.id, caption_override: draft.targets[a.id].custom ? draft.targets[a.id].override : null })),
    planned_platforms: [] as string[],
    schedule: draft.when ? { local_datetime: draft.when, timezone: browserTimezone() } : null,
  });

  async function run(label: string, action: () => Promise<Post | void>, success: string) {
    if (busy) return;
    setBusy(label);
    try {
      const result = await action();
      if (result) {
        setPost(result);
        setDraft(toDraft(result));
        if (!postId) router.replace(`/compose?id=${result.id}`);
      }
      setNotice(success);
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "That didn't work. Please try again.");
    } finally {
      setBusy("");
    }
  }

  // Save the current edits, then optionally take an action on the saved post.
  const save = async (action: "draft" | "submit" | "schedule"): Promise<Post> => {
    if (!post) {
      return api<Post>("/api/posts", { method: "POST", json: { ...payload(), action, reviewer_user_id: draft.reviewer || null } }, "Unable to save the post");
    }
    let saved = await api<Post>(`/api/posts/${post.id}`, { method: "PATCH", json: payload() }, "Unable to save the post");
    if (action === "submit") saved = await api<Post>(`/api/posts/${post.id}/submit`, { method: "POST", json: { reviewer_user_id: draft.reviewer, message: reviewNote } }, "Unable to send for review");
    if (action === "schedule" && saved.status !== "scheduled") saved = await api<Post>(`/api/posts/${post.id}/schedule`, { method: "POST", json: { schedule: payload().schedule } }, "Unable to schedule");
    return saved;
  };

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    setBusy("upload");
    try {
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        const asset = await api<Asset>("/api/assets", { method: "POST", body }, `Unable to upload ${file.name}`);
        setLibrary((current) => [asset, ...current]);
        setDraft((current) => ({ ...current, assetIds: [...current.assetIds, asset.id] }));
      }
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "Upload failed.");
    } finally {
      setBusy("");
    }
  }

  async function generateCaptions() {
    const platforms = Array.from(new Set(selectedAccounts.map((a) => a.platform)));
    if (!platforms.length) { setNotice("Choose at least one account first."); return; }
    await run("ai", async () => {
      const result = await api<{ posts: { platform: string; caption: string; hashtags: string[] }[] }>("/api/ai/captions", {
        method: "POST",
        json: { topic: draft.title || draft.caption || "Social media post", audience: aiAudience || "Our followers", instructions: draft.caption, platforms },
      }, "Caption generation failed");
      const byPlatform = Object.fromEntries(result.posts.map((p) => [p.platform, `${p.caption}${p.hashtags.length ? "\n\n" + p.hashtags.map((h) => `#${h.replace(/^#/, "")}`).join(" ") : ""}`]));
      setDraft((current) => {
        const first = result.posts[0];
        const targets = { ...current.targets };
        for (const account of selectedAccounts) {
          if (platforms.length > 1) targets[account.id] = { custom: true, override: byPlatform[account.platform] ?? "" };
        }
        return { ...current, caption: platforms.length === 1 && first ? byPlatform[first.platform] : current.caption, targets };
      });
    }, "AI drafts added. Review every detail before publishing.");
  }

  if (loading) return <p className="schedule-state">Loading the post…</p>;
  if (!editable) return <p className="schedule-state">Only owners, admins and editors can edit posts.</p>;

  return <div className="compose-layout">
    <section className="panel compose-main">
      <div className="section-card-heading">
        <div><span className="calendar-month-label">{post ? `${statusLabels[status].toUpperCase()} · ${formatWhen(post.scheduled_at)}` : "NEW POST"}</span>
          <h2>{post ? post.title || "Untitled post" : "Create a post"}</h2></div>
        <Link href="/posts" className="button button-outline">All posts</Link>
      </div>
      {locked && <p className="compose-note">This post has been sent to the platforms and can no longer be edited.</p>}
      {post?.status === "in_review" && <p className="compose-note">Waiting for {post.reviewer_name ?? "the reviewer"}. Saving changes sends it back to draft.</p>}

      <label className="compose-field"><span>INTERNAL TITLE</span>
        <input value={draft.title} maxLength={200} disabled={locked} placeholder="e.g. Ramadan offer week 1" onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
      <label className="compose-field"><span>CAPTION <small>{draft.caption.length.toLocaleString()} characters</small></span>
        <textarea rows={6} value={draft.caption} disabled={locked} placeholder="Write the post…" onChange={(e) => setDraft({ ...draft, caption: e.target.value })} /></label>
      {!locked && <div className="compose-ai">
        <input placeholder="Audience for AI (e.g. families in Lahore)" value={aiAudience} onChange={(e) => setAiAudience(e.target.value)} aria-label="Audience for AI captions" />
        <button type="button" className="button button-outline" disabled={Boolean(busy)} onClick={() => void generateCaptions()}>{busy === "ai" ? "Writing…" : "✦ Write with AI"}</button>
      </div>}

      <div className="compose-field"><span>MEDIA</span>
        <div className="compose-media">
          {selectedAssets.map((asset, index) => <div key={asset.id} className="compose-media-item">
            <MediaThumb asset={asset} />
            {!locked && <div className="compose-media-actions">
              <button type="button" aria-label="Move earlier" disabled={index === 0} onClick={() => setDraft((d) => { const ids = [...d.assetIds]; [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]]; return { ...d, assetIds: ids }; })}>←</button>
              <button type="button" aria-label={`Remove ${asset.filename}`} onClick={() => setDraft((d) => ({ ...d, assetIds: d.assetIds.filter((id) => id !== asset.id) }))}>✕</button>
            </div>}
          </div>)}
          {!locked && <>
            <button type="button" className="compose-add" onClick={() => setShowLibrary(!showLibrary)}>＋ From library</button>
            <label className="compose-add">{busy === "upload" ? "Uploading…" : "⇪ Upload"}<input type="file" hidden multiple accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime" onChange={(e) => void uploadFiles(e)} /></label>
          </>}
        </div>
        {showLibrary && <div className="compose-library">{library.length === 0 ? <small>Your library is empty. Upload something first.</small> : library.map((asset) => {
          const chosen = draft.assetIds.includes(asset.id);
          return <button type="button" key={asset.id} className={chosen ? "library-pick library-picked" : "library-pick"} onClick={() => setDraft((d) => ({ ...d, assetIds: chosen ? d.assetIds.filter((id) => id !== asset.id) : [...d.assetIds, asset.id] }))}>
            <MediaThumb asset={asset} size={64} /><small>{asset.filename}</small></button>;
        })}</div>}
      </div>

      <div className="compose-field"><span>PUBLISH TO</span>
        {accounts.length === 0 && <small>No accounts connected. <Link href="/accounts">Connect Facebook & Instagram</Link>.</small>}
        {accounts.map((account) => {
          const target = draft.targets[account.id];
          const limit = captionLimit[account.platform];
          const text = target?.custom ? target.override : draft.caption;
          return <div key={account.id} className="compose-target">
            <label className="compose-target-row">
              <input type="checkbox" disabled={locked} checked={Boolean(target)} onChange={() => setDraft((d) => {
                const targets = { ...d.targets };
                if (targets[account.id]) delete targets[account.id]; else targets[account.id] = { override: "", custom: false };
                return { ...d, targets };
              })} />
              <b>{account.platform === "instagram" ? `@${account.account_name}` : account.account_name}</b>
              <small>{platformName[account.platform]}{account.status === "needs_reconnect" ? " · needs reconnect" : ""}</small>
              {target && <small className={text.length > limit ? "publish-error-text" : ""}>{text.length.toLocaleString()}/{limit.toLocaleString()}</small>}
            </label>
            {target && !locked && <label className="compose-custom"><input type="checkbox" checked={target.custom} onChange={() => setDraft((d) => ({ ...d, targets: { ...d.targets, [account.id]: { override: d.targets[account.id].override || d.caption, custom: !d.targets[account.id].custom } } }))} /> Different caption for {platformName[account.platform]}</label>}
            {target?.custom && <textarea rows={3} value={target.override} disabled={locked} onChange={(e) => setDraft((d) => ({ ...d, targets: { ...d.targets, [account.id]: { ...d.targets[account.id], override: e.target.value } } }))} />}
          </div>;
        })}
      </div>

      {post && post.issues.length > 0 && <div className="compose-issues" role="alert"><b>Fix before publishing</b>
        <ul>{post.issues.map((issue, i) => <li key={i}>{issue.account ? `${issue.account}: ` : ""}{issue.message}</li>)}</ul></div>}
    </section>

    <aside className="panel compose-side">
      {!locked && <>
        <label className="compose-field"><span>WHEN ({browserTimezone()})</span>
          <input type="datetime-local" value={draft.when} onChange={(e) => setDraft({ ...draft, when: e.target.value })} /></label>
        <label className="compose-field"><span>REVIEWER (OPTIONAL)</span>
          <select value={draft.reviewer} onChange={(e) => setDraft({ ...draft, reviewer: e.target.value })}>
            <option value="">No review needed</option>
            {reviewers.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name} ({m.role})</option>)}
          </select></label>
        {draft.reviewer && <textarea rows={2} placeholder="Note for the reviewer (optional)" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} />}
      </>}
      <div className="compose-actions">
        {!locked && <button type="button" className="button button-outline" disabled={Boolean(busy)} onClick={() => void run("save", () => save("draft"), "Saved.")}>{busy === "save" ? "Saving…" : "Save draft"}</button>}
        {!locked && draft.reviewer && ["draft", "changes_requested", "rejected", "approved"].includes(status) && <button type="button" className="button button-primary" disabled={Boolean(busy)} onClick={() => void run("submit", () => save("submit"), "Sent for review.")}>Send for review</button>}
        {!locked && canScheduleNow && !(draft.reviewer && !hasReviewer) && <button type="button" className="button button-primary" disabled={Boolean(busy) || !draft.when} onClick={() => void run("schedule", () => save("schedule"), "Scheduled.")}>{status === "scheduled" ? "Save schedule" : "Schedule"}</button>}
        {!locked && canScheduleNow && !(draft.reviewer && !hasReviewer) && <button type="button" className="button button-outline" disabled={Boolean(busy)} onClick={() => void run("now", async () => { const saved = await save("draft"); await api(`/api/posts/${saved.id}/publish-now`, { method: "POST" }, "Unable to publish"); return api<Post>(`/api/posts/${saved.id}`); }, "Sent to the platforms. Status updates below.")}>Publish now</button>}
        {status === "scheduled" && <button type="button" className="button button-outline" disabled={Boolean(busy)} onClick={() => void run("unschedule", () => api<Post>(`/api/posts/${post!.id}/unschedule`, { method: "POST" }), "Unscheduled.")}>Unschedule</button>}
        {post?.targets.some((t) => t.status === "failed") && <button type="button" className="button button-primary" disabled={Boolean(busy)} onClick={() => void run("retry", async () => { await api(`/api/posts/${post.id}/retry`, { method: "POST" }, "Unable to retry"); return api<Post>(`/api/posts/${post.id}`); }, "Retrying the failed accounts.")}>Retry failed</button>}
        {(status === "publishing" || status === "scheduled") && post && <button type="button" className="button button-outline" disabled={Boolean(busy)} onClick={() => void run("refresh", () => api<Post>(`/api/posts/${post.id}`), "Status refreshed.")}>Refresh status</button>}
        {post && !locked && <button type="button" className="button-danger" disabled={Boolean(busy)} onClick={() => void run("delete", async () => { await api(`/api/posts/${post.id}`, { method: "DELETE" }, "Unable to delete"); router.push("/posts"); }, "Post deleted.")}>Delete post</button>}
      </div>

      {post && post.targets.length > 0 && <div className="compose-status"><span className="calendar-month-label">PUBLISHING</span>
        {post.targets.map((t) => <div key={t.id} className="compose-status-row">
          <b>{t.platform === "instagram" ? `@${t.account_name}` : t.account_name}</b>
          <span className={`pending-tag status-${t.status === "queued" || t.status === "pending" ? "scheduled" : t.status}`}><i /> {t.status === "queued" ? (t.attempts ? "Will retry" : "Queued") : t.status === "pending" ? "Not scheduled" : t.status[0].toUpperCase() + t.status.slice(1)}</span>
          {t.external_url && <a href={t.external_url} target="_blank" rel="noreferrer">View post ↗</a>}
          {t.last_error && <small className="publish-error-text">{t.last_error}</small>}
          {t.next_attempt_at && t.status === "queued" && <small>Next attempt {formatWhen(t.next_attempt_at)}</small>}
        </div>)}
      </div>}

      {post && <div className="compose-history"><span className="calendar-month-label">HISTORY</span>
        {post.events.map((e) => <div key={e.id}><b>{eventLabel[e.kind] ?? e.kind}</b>{e.actor_name ? ` · ${e.actor_name}` : ""} <small>{formatWhen(e.created_at)}</small>{e.message && <p>{e.kind === "scheduled" ? formatWhen(e.message) : e.message}</p>}</div>)}
        <form className="compose-comment" onSubmit={(e) => { e.preventDefault(); if (comment.trim()) void run("comment", async () => { const updated = await api<Post>(`/api/posts/${post.id}/comments`, { method: "POST", json: { message: comment } }); setComment(""); return updated; }, "Comment added."); }}>
          <input placeholder="Add a comment" value={comment} onChange={(e) => setComment(e.target.value)} aria-label="Comment" />
        </form>
      </div>}
    </aside>
  </div>;
}
