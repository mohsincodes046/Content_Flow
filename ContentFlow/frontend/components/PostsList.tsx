"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, assetUrl, formatWhen, statusLabels, type Post, type PostStatus } from "../lib/api";

const filters: { label: string; statuses: PostStatus[] | null }[] = [
  { label: "All", statuses: null },
  { label: "Drafts", statuses: ["draft", "changes_requested", "rejected"] },
  { label: "In review", statuses: ["in_review", "approved"] },
  { label: "Scheduled", statuses: ["scheduled", "publishing"] },
  { label: "Published", statuses: ["published", "partially_published"] },
  { label: "Failed", statuses: ["failed", "partially_published"] },
];

export function StatusPill({ status }: { status: PostStatus }) {
  return <span className={`post-status post-status-${status}`}>{statusLabels[status]}</span>;
}

export function PostThumb({ post }: { post: Post }) {
  const first = post.media[0];
  if (!first) return <span className="post-thumb post-thumb-text">Aa</span>;
  return first.media_type.startsWith("video/")
    ? <span className="post-thumb post-thumb-text">▶</span>
    // eslint-disable-next-line @next/next/no-img-element
    : <img className="post-thumb" src={assetUrl(first.id)} alt="" />;
}

export default function PostsList({ setNotice }: { setNotice: (value: string) => void }) {
  const [posts, setPosts] = useState<Post[] | null>(null);
  const [filter, setFilter] = useState(0);

  useEffect(() => {
    let active = true;
    const statuses = filters[filter].statuses;
    api<Post[]>(`/api/posts${statuses ? `?status=${statuses.join(",")}` : ""}`, {}, "Unable to load posts")
      .then((loaded) => { if (active) setPosts(loaded); })
      .catch((failure: unknown) => setNotice(failure instanceof Error ? failure.message : "Unable to load posts."));
    return () => { active = false; };
  }, [filter, setNotice]);

  return <section className="panel posts-panel">
    <div className="section-card-heading">
      <div><span className="calendar-month-label">EVERYTHING YOU&apos;RE WORKING ON</span><h2>Posts</h2></div>
      <Link href="/compose" className="button button-primary">＋ New post</Link>
    </div>
    <div className="media-filter">{filters.map((f, i) => <button key={f.label} type="button" className={`filter-pill ${i === filter ? "filter-active" : ""}`} onClick={() => setFilter(i)}>{f.label}</button>)}</div>
    {posts === null && <p className="schedule-state">Loading posts…</p>}
    {posts?.length === 0 && <div className="upcoming-empty"><b>Nothing here yet.</b><p>Create a post to start planning.</p></div>}
    <div className="posts-list">{posts?.map((post) => {
      const failed = post.targets.filter((t) => t.status === "failed");
      return <Link key={post.id} href={`/compose?id=${post.id}`} className="post-row">
        <PostThumb post={post} />
        <span className="post-row-text">
          <b>{post.title || post.caption.split("\n")[0] || "Untitled post"}</b>
          <small>{formatWhen(post.scheduled_at)} · {post.targets.length ? post.targets.map((t) => t.platform === "instagram" ? `@${t.account_name}` : t.account_name).join(", ") : post.planned_platforms.length ? `Planned: ${post.planned_platforms.join(", ")}` : "No accounts yet"}</small>
          {failed.length > 0 && <small className="publish-error-text">{failed[0].last_error}</small>}
          {post.issues.length > 0 && !failed.length && <small className="account-note">{post.issues.length} thing{post.issues.length === 1 ? "" : "s"} to fix before publishing</small>}
        </span>
        <StatusPill status={post.status} />
      </Link>;
    })}</div>
  </section>;
}
