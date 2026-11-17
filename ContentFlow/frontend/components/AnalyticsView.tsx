"use client";

import { useEffect, useState } from "react";
import { api, formatWhen, statusLabels, type PostStatus } from "../lib/api";

type Metric = { key: string; label: string; value: number | null; available: boolean; note?: string | null };
type AccountReport = {
  account_id: string; platform: string; account_name: string; profile_picture_url?: string | null;
  metrics: Metric[]; followers: number | null; fetched_at: string | null; error?: string | null; cached: boolean;
};
type PostReport = {
  post_id: string; title: string; platform: string; account_name: string; published_at: string;
  external_url?: string | null; metrics: Metric[]; error?: string | null;
};
type Summary = { days: number; posts_by_status: Record<string, number>; attempts: Record<string, number> };

const fmt = (value: number | null) => value === null ? "—" : Math.round(value).toLocaleString();

function MetricTile({ metric }: { metric: Metric }) {
  return <div className={`metric-tile ${metric.available ? "" : "metric-unavailable"}`} title={metric.note ?? undefined}>
    <b>{metric.available ? fmt(metric.value) : "Unavailable"}</b>
    <span>{metric.label}</span>
    {!metric.available && metric.note && <small>{metric.note}</small>}
  </div>;
}

export default function AnalyticsView({ setNotice }: { setNotice: (value: string) => void }) {
  const [days, setDays] = useState(28);
  const [accounts, setAccounts] = useState<AccountReport[] | null>(null);
  const [posts, setPosts] = useState<PostReport[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = refreshKey > 0 ? "&refresh=true" : "";
    Promise.all([
      api<AccountReport[]>(`/api/analytics/accounts?days=${days}${refresh}`, {}, "Unable to load account insights"),
      api<PostReport[]>(`/api/analytics/posts?days=${Math.max(days, 30)}${refresh}`, {}, "Unable to load post insights"),
      api<Summary>(`/api/analytics/summary?days=${days}`, {}, "Unable to load the publishing summary"),
    ]).then(([a, p, s]) => {
      if (!active) return;
      setAccounts(a); setPosts(p); setSummary(s);
    }).catch((failure: unknown) => {
      if (active) setNotice(failure instanceof Error ? failure.message : "Unable to load analytics.");
    }).finally(() => { if (active) setRefreshing(false); });
    return () => { active = false; };
  }, [days, refreshKey, setNotice]);

  const lastFetched = accounts?.map((a) => a.fetched_at).filter(Boolean).sort().at(-1) ?? null;

  return <div className="analytics-view">
    <div className="analytics-toolbar">
      <div className="media-filter">{[7, 28, 30].map((d) => <button key={d} type="button" className={`filter-pill ${d === days ? "filter-active" : ""}`} onClick={() => setDays(d)}>Last {d} days</button>)}</div>
      <span className="analytics-meta">{lastFetched ? `Updated ${formatWhen(lastFetched)}` : ""}</span>
      <button type="button" className="button button-outline" disabled={refreshing} onClick={() => { setRefreshing(true); setRefreshKey((k) => k + 1); }}>{refreshing ? "Refreshing…" : "Refresh from Meta"}</button>
    </div>

    <section className="panel analytics-section">
      <span className="calendar-month-label">ACCOUNTS · LAST {days} DAYS</span>
      {accounts === null && <p className="schedule-state">Loading insights from Meta…</p>}
      {accounts?.length === 0 && <div className="upcoming-empty"><b>No accounts connected.</b><p>Connect a Facebook Page or Instagram account to see its insights.</p></div>}
      {accounts?.map((account) => <article key={account.account_id} className="analytics-account">
        <div className="analytics-account-head">
          <b>{account.platform === "instagram" ? `@${account.account_name}` : account.account_name}</b>
          <small>{account.platform === "instagram" ? "Instagram" : "Facebook Page"}{account.followers !== null ? ` · ${account.followers.toLocaleString()} followers` : ""}</small>
        </div>
        {account.error ? <p className="publish-error-text">{account.error}</p>
          : <div className="metric-grid">{account.metrics.map((m) => <MetricTile key={m.key} metric={m} />)}</div>}
      </article>)}
      <p className="analytics-footnote">Figures come from Meta&apos;s insights API and may be estimated by Meta. &quot;Unavailable&quot; means Meta did not provide the figure (for example, a retired metric or too little activity); it is not zero.</p>
    </section>

    <section className="panel analytics-section">
      <span className="calendar-month-label">POSTS PUBLISHED WITH CONTENT FLOW</span>
      {posts === null && <p className="schedule-state">Loading post performance…</p>}
      {posts?.length === 0 && <p className="schedule-state">No posts were published in this period.</p>}
      {posts?.map((post) => <article key={`${post.post_id}-${post.account_name}`} className="analytics-post">
        <div className="analytics-account-head">
          <b>{post.title}</b>
          <small>{post.platform === "instagram" ? `@${post.account_name}` : post.account_name} · {formatWhen(post.published_at)}{post.external_url ? <> · <a href={post.external_url} target="_blank" rel="noreferrer">View ↗</a></> : null}</small>
        </div>
        {post.error ? <p className="publish-error-text">{post.error}</p>
          : <div className="metric-grid">{post.metrics.map((m) => <MetricTile key={m.key} metric={m} />)}</div>}
      </article>)}
    </section>

    {summary && <section className="panel analytics-section">
      <span className="calendar-month-label">PUBLISHING ACTIVITY</span>
      <div className="metric-grid">
        {(["scheduled", "published", "partially_published", "failed", "in_review", "draft"] as PostStatus[]).map((s) =>
          <div key={s} className="metric-tile"><b>{(summary.posts_by_status[s] ?? 0).toLocaleString()}</b><span>{statusLabels[s]}</span></div>)}
        <div className="metric-tile"><b>{(summary.attempts.retry ?? 0).toLocaleString()}</b><span>Automatic retries ({days} days)</span></div>
      </div>
    </section>}
  </div>;
}
