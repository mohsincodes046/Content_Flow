"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import SubmissionWorkflow from "./SubmissionWorkflow";
import { StatusPill } from "./PostsList";
import { api, assetUrl, canEditContent, canReview, formatWhen, type Post, type SessionUser } from "../lib/api";

const kindLabel: Record<string, string> = {
  submitted: "Sent for review", approved: "Approved", rejected: "Rejected", changes_requested: "Changes requested",
  comment: "Comment", edited: "Edited", created: "Created", scheduled: "Scheduled", published: "Published",
};

function ReviewCard({ post, user, onChange, setNotice }: { post: Post; user: SessionUser; onChange: (p: Post) => void; setNotice: (v: string) => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const mayDecide = post.status === "in_review" && (post.reviewer_user_id === user.id || user.role === "owner" || user.role === "admin");

  async function act(path: string, json: unknown, success: string) {
    setBusy(true);
    try {
      onChange(await api<Post>(`/api/posts/${post.id}/${path}`, { method: "POST", json }, "Unable to save your review"));
      setComment("");
      setNotice(success);
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "Unable to save your review.");
    } finally {
      setBusy(false);
    }
  }

  return <article className="panel review-card">
    <div className="review-card-head">
      <div><b>{post.title || "Post for review"}</b><small>{formatWhen(post.scheduled_at)} · from {post.created_by_name ?? "the team"}{post.reviewer_name ? ` · reviewer ${post.reviewer_name}` : ""}</small></div>
      <StatusPill status={post.status} />
    </div>
    <div className="review-media">{post.media.map((m) => m.media_type.startsWith("video/")
      ? <video key={m.id} src={assetUrl(m.id)} controls />
      // eslint-disable-next-line @next/next/no-img-element
      : <img key={m.id} src={assetUrl(m.id)} alt={m.filename} />)}</div>
    {post.targets.length > 0 ? post.targets.map((t) => <div key={t.id} className="review-version">
      <span className="calendar-month-label">{t.platform.toUpperCase()} · {t.platform === "instagram" ? `@${t.account_name}` : t.account_name}</span>
      <p>{t.caption_override ?? post.caption}</p>
    </div>) : <p className="review-version">{post.caption}</p>}
    {post.events.length > 0 && <div className="review-history">{post.events.filter((e) => kindLabel[e.kind]).map((e) => <div key={e.id}><b>{kindLabel[e.kind]}</b>{e.actor_name ? ` · ${e.actor_name}` : ""} <small>{formatWhen(e.created_at)}</small>{e.message && <p>{e.kind === "scheduled" ? formatWhen(e.message) : e.message}</p>}</div>)}</div>}
    <textarea rows={2} placeholder={mayDecide ? "Comment (required to reject or request changes)" : "Add a comment"} value={comment} onChange={(e) => setComment(e.target.value)} aria-label="Review comment" />
    <div className="compose-actions">
      {mayDecide && <>
        <button type="button" className="button button-primary" disabled={busy} onClick={() => void act("review", { decision: "approve", comment }, "Approved.")}>Approve</button>
        <button type="button" className="button button-outline" disabled={busy || !comment.trim()} onClick={() => void act("review", { decision: "request_changes", comment }, "Changes requested.")}>Request changes</button>
        <button type="button" className="button-danger" disabled={busy || !comment.trim()} onClick={() => void act("review", { decision: "reject", comment }, "Rejected.")}>Reject</button>
      </>}
      <button type="button" className="button button-outline" disabled={busy || !comment.trim()} onClick={() => void act("comments", { message: comment }, "Comment added.")}>Comment</button>
      {canEditContent(user.role) && <Link href={`/compose?id=${post.id}`} className="button button-outline">Open in editor</Link>}
    </div>
  </article>;
}

export default function ReviewQueue({ user, setNotice }: { user: SessionUser; setNotice: (value: string) => void }) {
  const [posts, setPosts] = useState<Post[] | null>(null);
  const [tab, setTab] = useState<"approvals" | "requests">("approvals");
  const isClient = user.role === "client";

  useEffect(() => {
    let active = true;
    const statuses = isClient ? "in_review,changes_requested,approved,rejected,scheduled,published,partially_published" : "in_review,changes_requested";
    api<Post[]>(`/api/posts?status=${statuses}`, {}, "Unable to load the review queue")
      .then(async (list) => {
        // The list omits history; load each post's details for the cards.
        const detailed = await Promise.all(list.map((p) => api<Post>(`/api/posts/${p.id}`)));
        if (active) setPosts(detailed);
      })
      .catch((failure: unknown) => setNotice(failure instanceof Error ? failure.message : "Unable to load the review queue."));
    return () => { active = false; };
  }, [isClient, setNotice]);

  const waiting = posts?.filter((p) => p.status === "in_review") ?? [];
  const others = posts?.filter((p) => p.status !== "in_review") ?? [];
  const replace = (updated: Post) => setPosts((current) => current?.map((p) => p.id === updated.id ? updated : p) ?? null);

  return <div className="review-queue">
    {!isClient && <div className="media-filter">
      <button type="button" className={`filter-pill ${tab === "approvals" ? "filter-active" : ""}`} onClick={() => setTab("approvals")}>Approvals</button>
      {canReview(user.role) || canEditContent(user.role) ? <button type="button" className={`filter-pill ${tab === "requests" ? "filter-active" : ""}`} onClick={() => setTab("requests")}>Content requests</button> : null}
    </div>}
    {tab === "requests" ? <SubmissionWorkflow view="review" setNotice={setNotice} /> : <>
      {posts === null && <p className="schedule-state">Loading…</p>}
      {posts !== null && waiting.length === 0 && <section className="panel upcoming-empty"><b>Nothing to review right now.</b><p>{isClient ? "Content your agency sends you for approval will appear here." : "Posts sent for review appear here."}</p></section>}
      {waiting.map((post) => <ReviewCard key={post.id} post={post} user={user} onChange={replace} setNotice={setNotice} />)}
      {others.length > 0 && <><h3 className="review-subhead">{isClient ? "Reviewed earlier" : "Waiting for the team"}</h3>
        {others.map((post) => <ReviewCard key={post.id} post={post} user={user} onChange={replace} setNotice={setNotice} />)}</>}
    </>}
  </div>;
}
