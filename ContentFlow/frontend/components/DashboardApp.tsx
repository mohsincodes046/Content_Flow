"use client";

import Link from "next/link";
import Image from "next/image";
import { useCallback, useMemo, useState, useSyncExternalStore, type ChangeEvent, type DragEvent } from "react";
import Logo from "./Logo";

type MediaItem = { id: string; name: string; url: string; kind: "image" | "video" };
type ScheduledPost = { id: string; mediaName: string; date: string; time: string; platform: string[]; caption: string };
type SocialAccount = { id: string; label: string; handle: string; color: string; icon: string };

const accounts: SocialAccount[] = [
  { id: "instagram", label: "Instagram", handle: "@goodthings.studio", color: "#e76072", icon: "◎" },
  { id: "facebook", label: "Facebook", handle: "Good Things Studio", color: "#4d76e9", icon: "f" },
  { id: "tiktok", label: "TikTok", handle: "@goodthings", color: "#1c1c20", icon: "♪" },
  { id: "linkedin", label: "LinkedIn", handle: "Good Things Studio", color: "#3285bd", icon: "in" },
  { id: "youtube", label: "YouTube", handle: "@goodthingsstudio", color: "#e8584d", icon: "▶" },
];

const navigation = [
  { label: "Overview", href: "/dashboard", icon: "grid", section: "WORKSPACE" },
  { label: "Content library", href: "/content", icon: "image" },
  { label: "Calendar", href: "/calendar", icon: "calendar" },
  { label: "Bulk schedule", href: "/bulk-schedule", icon: "stack", badge: "CORE" },
  { label: "Create a post", href: "/create-post", icon: "plus" },
  { label: "AI captions", href: "/ai-captions", icon: "spark" },
  { label: "Analytics", href: "/analytics", icon: "chart", section: "MANAGE" },
  { label: "Social accounts", href: "/accounts", icon: "share" },
  { label: "Team", href: "/team", icon: "users" },
  { label: "Settings", href: "/settings", icon: "settings" },
];

const demoMedia = [
  { name: "Morning ritual.jpg", type: "photo", label: "☼", className: "tile-sunrise" },
  { name: "Sunday market.jpg", type: "photo", label: "✿", className: "tile-market" },
  { name: "Studio moments.mp4", type: "video", label: "▶", className: "tile-studio" },
  { name: "A little reminder.jpg", type: "photo", label: "✳", className: "tile-reminder" },
];

const makeId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
const localDate = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const todayString = () => localDate(new Date());
const subscribeToSavedPosts = (onChange: () => void) => {
  window.addEventListener("socialpilot-posts-updated", onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener("socialpilot-posts-updated", onChange);
    window.removeEventListener("storage", onChange);
  };
};
const getSavedPostsSnapshot = () => window.localStorage.getItem("socialpilot-posts") ?? "[]";
const getEmptyPostsSnapshot = () => "[]";
const parseSavedPosts = (saved: string): ScheduledPost[] => {
  try {
    const posts: unknown = JSON.parse(saved);
    if (!Array.isArray(posts)) throw new Error("Saved schedules must be a list of posts.");
    return posts as ScheduledPost[];
  } catch (error) {
    console.error("Unable to parse saved schedules.", error);
    return [];
  }
};
const friendlyDate = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString("en", { weekday: "short", month: "short", day: "numeric" });

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const shapes: Record<string, React.ReactNode> = {
    grid: <><rect x="3.5" y="3.5" width="7" height="7" rx="2" /><rect x="13.5" y="3.5" width="7" height="7" rx="2" /><rect x="3.5" y="13.5" width="7" height="7" rx="2" /><rect x="13.5" y="13.5" width="7" height="7" rx="2" /></>,
    image: <><rect x="3" y="4" width="18" height="16" rx="3" /><circle cx="8.7" cy="9" r="1.6" /><path d="m4 17 5-5 3.4 3.4 3.1-3.1L21 18" /></>,
    calendar: <><rect x="3.5" y="5.5" width="17" height="15" rx="2.5" /><path d="M7.5 3v5M16.5 3v5M4 10h16" /></>,
    stack: <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    spark: <><path d="m12 3 1.9 6.1L20 11l-6.1 1.9L12 19l-1.9-6.1L4 11l6.1-1.9L12 3Z" /><path d="m19 15 1.1 2.9L23 19l-2.9 1.1L19 23l-1.1-2.9L15 19l2.9-1.1L19 15Z" /></>,
    chart: <><path d="M4 19V5m0 14h17" /><path d="m7 15 4-4 3 2 6-7" /><path d="M17 6h3v3" /></>,
    share: <><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="m8.7 10.5 6.6-4m-6.6 9 6.6 4" /></>,
    users: <><path d="M16 20v-1.5a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20" /><circle cx="9.5" cy="8" r="3.5" /><path d="M17 11a3.5 3.5 0 1 0 0-7m4 16v-1.5a4 4 0 0 0-3-3.9" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="m19.4 15 .1.1 1.4 1.1-1.5 2.6-1.7-.7a8 8 0 0 1-1.8 1l-.3 1.9h-3l-.3-1.9a8 8 0 0 1-1.8-1l-1.7.7-1.5-2.6L6.7 15a8 8 0 0 1 0-2l-1.4-1.1 1.5-2.6 1.7.7a8 8 0 0 1 1.8-1l.3-1.9h3l.3 1.9a8 8 0 0 1 1.8 1l1.7-.7 1.5 2.6-1.4 1.1a8 8 0 0 1-.1 2Z" /></>,
    bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
    search: <><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.2 4.2" /></>,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
    upload: <><path d="M12 16V4m0 0L7 9m5-5 5 5" /><path d="M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    close: <><path d="m18 6-12 12M6 6l12 12" /></>,
    more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
    heart: <path d="M20.8 8.8c0 4.6-8.8 10-8.8 10S3.2 13.4 3.2 8.8a4.6 4.6 0 0 1 8.8-2.2 4.6 4.6 0 0 1 8.8 2.2Z" />,
    play: <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="m10 9 5 3-5 3V9Z" /></>,
    down: <path d="m7 10 5 5 5-5" />,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  };
  return <svg aria-hidden="true" className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{shapes[name] ?? shapes.spark}</svg>;
}

export default function DashboardApp({ section }: { section: string }) {
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [captionEdits, setCaptionEdits] = useState<Record<string, string>>({});
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>(["instagram", "tiktok"]);
  const [startDate, setStartDate] = useState(todayString);
  const [endDate, setEndDate] = useState("");
  const [frequency, setFrequency] = useState("daily");
  const [customDays, setCustomDays] = useState<number[]>([1, 3, 5]);
  const [time, setTime] = useState("10:00");
  const [notice, setNotice] = useState("");
  const [draggedPost, setDraggedPost] = useState<number | null>(null);
  const [showNotifications, setShowNotifications] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const savedPostsSnapshot = useSyncExternalStore(subscribeToSavedPosts, getSavedPostsSnapshot, getEmptyPostsSnapshot);
  const posts = useMemo(() => parseSavedPosts(savedPostsSnapshot), [savedPostsSnapshot]);
  const removeMedia = useCallback((id: string) => {
    const item = media.find((entry) => entry.id === id);
    if (item) URL.revokeObjectURL(item.url);
    setMedia((current) => current.filter((entry) => entry.id !== id));
    setSelected((current) => current.filter((entry) => entry !== id));
  }, [media]);

  const uploadFiles = useCallback((files: FileList | File[]) => {
    const accepted = Array.from(files).filter((file) => (file.type.startsWith("image/") || file.type.startsWith("video/")) && file.size <= 50 * 1024 * 1024);
    if (accepted.length !== files.length) setNotice("A few files were skipped. Choose image or video files under 50 MB each.");
    if (accepted.length) {
      const added = accepted.map((file) => ({ id: makeId(), name: file.name, url: URL.createObjectURL(file), kind: file.type.startsWith("video/") ? "video" as const : "image" as const }));
      setMedia((current) => [...current, ...added]);
      setSelected((current) => [...current, ...added.map((item) => item.id)]);
      if (accepted.length === files.length) setNotice("");
    }
  }, []);

  const onUploadChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files?.length) uploadFiles(event.target.files);
    event.target.value = "";
  };

  const days = useMemo(() => {
    if (!startDate || (endDate && endDate < startDate)) return [];
    const last = endDate || (() => {
      const date = new Date(`${startDate}T12:00:00`);
      date.setDate(date.getDate() + 29);
      return localDate(date);
    })();
    const first = new Date(`${startDate}T12:00:00`);
    const final = new Date(`${last}T12:00:00`);
    const result: string[] = [];
    for (const date = new Date(first); date <= final && result.length < 366; date.setDate(date.getDate() + 1)) result.push(localDate(date));
    return result;
  }, [startDate, endDate]);

  const preview = useMemo(() => {
    const eligibleDates = days.filter((date) => {
      const weekday = new Date(`${date}T12:00:00`).getDay();
      if (frequency === "three-weekly") return weekday === 1 || weekday === 3 || weekday === 5;
      if (frequency === "custom") return customDays.includes(weekday);
      return true;
    });
    return selected.map((mediaId, index) => {
      const item = media.find((entry) => entry.id === mediaId);
      const date = eligibleDates[index];
      if (!item || !date) return null;
      const label = item.name.replace(/\.[^.]+$/, "").replace(/[-_]/g, " ");
      const id = `${mediaId}-${date}`;
      return { id, mediaId, mediaName: item.name, mediaKind: item.kind, mediaUrl: item.url, date, time, platform: selectedAccounts, caption: captionEdits[id] ?? `A little moment worth remembering. ${label.toLowerCase()} ✨\n\n#GoodThings #LittleMoments #MadeForYou` };
    }).filter((post): post is NonNullable<typeof post> => post !== null);
  }, [days, frequency, customDays, selected, media, time, selectedAccounts, captionEdits]);

  const expectedCount = useMemo(() => days.filter((date) => {
    const weekday = new Date(`${date}T12:00:00`).getDay();
    if (frequency === "three-weekly") return weekday === 1 || weekday === 3 || weekday === 5;
    if (frequency === "custom") return customDays.includes(weekday);
    return true;
  }).length, [days, frequency, customDays]);
  const blocked = useMemo(() => preview.some((candidate) => posts.some((saved) => saved.date === candidate.date && saved.time === candidate.time && saved.platform.some((platform) => candidate.platform.includes(platform)))), [preview, posts]);
  const sectionName = navigation.find((item) => item.href === `/${section}`)?.label ?? "Overview";
  const title = section === "bulk-schedule" ? "Bulk schedule" : sectionName;
  function saveSchedule() {
    if (preview.length === 0 || selectedAccounts.length === 0) {
      setNotice(selectedAccounts.length === 0 ? "Choose at least one social account before scheduling." : "Add some photos or videos first, then your schedule is ready.");
      return;
    }
    if (blocked) {
      setNotice("There's already a post planned for one of these accounts at the same time. Change the publishing time or edit your existing schedule.");
      return;
    }
    const newPosts: ScheduledPost[] = preview.map((post) => ({ id: post.id, mediaName: post.mediaName, date: post.date, time: post.time, platform: post.platform, caption: post.caption }));
    const next = [...posts, ...newPosts].sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
    try {
      window.localStorage.setItem("socialpilot-posts", JSON.stringify(next));
      window.dispatchEvent(new Event("socialpilot-posts-updated"));
      setNotice(`${newPosts.length} ${newPosts.length === 1 ? "post is" : "posts are"} on the calendar. Your content is all set.`);
    } catch (error) {
      console.error("Unable to save scheduled posts.", error);
      setNotice("Your schedule couldn't be saved in this browser. Try removing some uploaded items and schedule again.");
    }
  }

  function removePost(id: string) {
    const next = posts.filter((post) => post.id !== id);
    try {
      window.localStorage.setItem("socialpilot-posts", JSON.stringify(next));
      window.dispatchEvent(new Event("socialpilot-posts-updated"));
      setNotice("Post removed from your schedule.");
    } catch (error) {
      console.error("Unable to update saved schedules.", error);
      setNotice("Unable to remove the post. Please try again.");
    }
  }

  function reschedulePost(id: string, date: string) {
    const movingPost = posts.find((post) => post.id === id);
    if (!movingPost || movingPost.date === date) return;
    const collision = posts.some((post) => post.id !== id && post.date === date && post.time === movingPost.time && post.platform.some((platform) => movingPost.platform.includes(platform)));
    if (collision) {
      setNotice("There’s already a post planned for one of these channels at that time. Try another date.");
      return;
    }
    const next = posts.map((post) => post.id === id ? { ...post, date } : post).sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
    try {
      window.localStorage.setItem("socialpilot-posts", JSON.stringify(next));
      window.dispatchEvent(new Event("socialpilot-posts-updated"));
      setNotice(`Post moved to ${friendlyDate(date)}.`);
    } catch (error) {
      console.error("Unable to update the scheduled date.", error);
      setNotice("Unable to change the scheduled date. Please try again.");
    }
  }

  function movePost(source: number, target: number) {
    setSelected((current) => {
      const next = [...current];
      const [mediaId] = next.splice(source, 1);
      next.splice(target, 0, mediaId);
      return next;
    });
    setDraggedPost(null);
  }

  function updateCaption(id: string, caption: string) {
    setCaptionEdits((current) => ({ ...current, [id]: caption }));
  }

  const handleDragStart = (event: DragEvent<HTMLElement>, index: number) => {
    setDraggedPost(index);
    event.dataTransfer.effectAllowed = "move";
  };

  function toggleAccount(id: string) {
    setSelectedAccounts((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  const navContent = <><div className="sidebar-brand"><Logo href="/dashboard" /><button aria-label="Close navigation" className="mobile-close" onClick={() => setMobileOpen(false)}><Icon name="close" /></button></div><div className="workspace-switch"><div className="workspace-avatar">G</div><div><b>Good Things Studio</b><small>Free workspace</small></div><Icon name="down" size={15} /></div><nav className="side-nav">{navigation.map((item) => <div key={item.href}>{item.section && <div className="nav-section-label">{item.section}</div>}<Link href={item.href} onClick={() => setMobileOpen(false)} className={`nav-item ${section === item.href.slice(1) || (section === "create-post" && item.href === "/bulk-schedule") ? "nav-active" : ""}`}><Icon name={item.icon} /><span>{item.label}</span>{item.badge && <span className="nav-badge">{item.badge}</span>}</Link></div>)}</nav><div className="sidebar-bottom"><div className="plan-card"><div className="plan-card-top"><span className="plan-spark">✳</span><span>YOUR LITTLE CORNER</span></div><b>Ready to make a little more room?</b><p>Unlock more channels and plan further ahead.</p><button onClick={() => setNotice("Your workspace is on the free plan. Billing details will be available when a subscription is connected.")}>Explore plans <span>↗</span></button></div><Link href="/settings" className="user-profile"><div className="user-avatar">AM</div><span><b>Alex Morgan</b><small>Admin</small></span><Icon name="more" /></Link></div></>;

  return <div className="app-layout"><div className={`sidebar-backdrop ${mobileOpen ? "backdrop-visible" : ""}`} onClick={() => setMobileOpen(false)} /><aside className={`app-sidebar ${mobileOpen ? "sidebar-open" : ""}`}>{navContent}</aside><main className="dashboard-main"><header className="topbar"><div className="topbar-left"><button aria-label="Open navigation" className="mobile-menu-button" onClick={() => setMobileOpen(true)}><Icon name="menu" /></button><div className="breadcrumb"><span>Good Things Studio</span><span className="crumb-separator">/</span><b>{title}</b></div></div><div className="topbar-right"><button aria-label="Search your workspace" className="icon-button search-button" onClick={() => setNotice("Workspace search is ready when you have more content to explore.")}><Icon name="search" /></button><div className="notification-wrap"><button aria-label="Notifications" className={`icon-button notification-button ${showNotifications ? "icon-selected" : ""}`} onClick={() => setShowNotifications(!showNotifications)}><Icon name="bell" /><i /></button>{showNotifications && <div className="notification-popover"><b>You’re all caught up ✨</b><p>New post activity and account updates will show up here.</p><Link href="/calendar" onClick={() => setShowNotifications(false)}>See your calendar <span>↗</span></Link></div>}</div><span className="topbar-divider" /><Link href="/settings" className="topbar-avatar" aria-label="Open profile settings">AM</Link></div></header><div className="page-content">{section === "bulk-schedule" || section === "create-post" ? <BulkSchedule section={section} media={media} selected={selected} setSelected={setSelected} onFilesDrop={uploadFiles} onUploadChange={onUploadChange} startDate={startDate} setStartDate={setStartDate} endDate={endDate} setEndDate={setEndDate} frequency={frequency} setFrequency={setFrequency} customDays={customDays} setCustomDays={setCustomDays} time={time} setTime={setTime} accounts={accounts} selectedAccounts={selectedAccounts} toggleAccount={toggleAccount} preview={preview} expectedCount={expectedCount} onSave={saveSchedule} onMove={movePost} onRemovePreview={(id) => setSelected((current) => current.filter((item) => item !== id))} onCaptionChange={updateCaption} onDragStart={handleDragStart} draggedPost={draggedPost} blocked={blocked} setNotice={setNotice} /> : <SectionContent section={section} sectionName={sectionName} posts={posts} media={media} onUploadChange={onUploadChange} onRemoveMedia={removeMedia} accounts={accounts} onRemove={removePost} onReschedule={reschedulePost} setNotice={setNotice} />}<div className={`toast-notice ${notice ? "toast-show" : ""}`} role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")}><Icon name="close" size={15} /></button></div><footer className="app-footer"><span>Made for what you make. <span className="footer-spark">✳</span></span><span>Preview workspace · Sample data</span></footer></div></main></div>;
}

type BulkProps = {
  section: string; media: MediaItem[]; selected: string[]; setSelected: React.Dispatch<React.SetStateAction<string[]>>; onFilesDrop: (files: FileList | File[]) => void; onUploadChange: (event: ChangeEvent<HTMLInputElement>) => void;
  startDate: string; setStartDate: (value: string) => void; endDate: string; setEndDate: (value: string) => void; frequency: string; setFrequency: (value: string) => void; customDays: number[]; setCustomDays: React.Dispatch<React.SetStateAction<number[]>>; time: string; setTime: (value: string) => void;
  accounts: SocialAccount[]; selectedAccounts: string[]; toggleAccount: (id: string) => void; preview: Array<{ id: string; mediaId: string; mediaName: string; mediaKind: "image" | "video"; mediaUrl: string; date: string; time: string; platform: string[]; caption: string }>;
  expectedCount: number; onSave: () => void; onMove: (source: number, target: number) => void; onRemovePreview: (mediaId: string) => void; onCaptionChange: (id: string, caption: string) => void; onDragStart: (event: DragEvent<HTMLElement>, index: number) => void; draggedPost: number | null; blocked: boolean; setNotice: (value: string) => void;
};

function BulkSchedule(props: BulkProps) {
  const [view, setView] = useState<"all" | "images" | "videos">("all");
  const visibleMedia = props.media.filter((item) => view === "all" || item.kind === (view === "images" ? "image" : "video"));
  const selectMedia = (id: string) => props.setSelected((current) => current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id]);
  const toggleDay = (day: number) => props.setCustomDays((current) => current.includes(day) ? current.filter((item) => item !== day) : [...current, day].sort());
  const insufficientContent = props.selected.length > 0 && props.preview.length < props.expectedCount;

  return <><div className="page-heading"><div><div className="eyebrow page-eyebrow"><span className="live-dot" /> YOUR NEW FAVOURITE SHORTCUT</div><h1>{props.section === "create-post" ? "Create a post" : "A month of posts. Sorted."}</h1><p>Line up your content, pick your pace, and let your calendar fall into place.</p></div><div className="heading-actions"><Link href="/calendar" className="button button-white"><Icon name="calendar" size={17} /> Open calendar</Link></div></div>
    <div className="bulk-banner"><div className="banner-sticker">✳</div><div><b>Big batch of content? You’re in the right place.</b><span>Everything below is just a preview — nothing gets scheduled until you say so.</span></div><div className="banner-spark">✦</div></div>
    <div className="scheduler-layout"><div className="scheduler-primary"><section className="panel media-panel"><div className="panel-heading"><div><div className="step-label"><span>01</span> FIRST THINGS FIRST</div><h2>Pick your content</h2><p>Bring a little inspiration from your library.</p></div><label className="button button-outline upload-button"><Icon name="upload" size={16} /> Upload content<input aria-label="Upload images and videos" className="file-picker-input" type="file" accept="image/*,video/*" multiple onChange={props.onUploadChange} hidden /></label></div><div className="media-filter">{(["all", "images", "videos"] as const).map((item) => <button key={item} className={`filter-pill ${view === item ? "filter-active" : ""}`} onClick={() => setView(item)}>{item === "all" ? "Everything" : item === "images" ? "Photos" : "Videos"}</button>)}<span className="media-count">{props.media.length} items <span>·</span> {props.selected.length} selected</span></div>{visibleMedia.length === 0 ? <label className="upload-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (event.dataTransfer.files.length) props.onFilesDrop(event.dataTransfer.files); }}><div className="drop-icon"><Icon name="upload" size={23} /></div><b>Your next great post starts here.</b><span>Drop your photos and videos here, or browse your files.</span><span className="drop-formats">PNG, JPG, WEBP, GIF, MP4, MOV · up to 50 MB each</span></label> : <div className="media-grid">{visibleMedia.map((item) => { const active = props.selected.includes(item.id); return <button aria-label={`${active ? "Deselect" : "Select"} ${item.name}`} key={item.id} className={`media-tile ${active ? "media-selected" : ""}`} onClick={() => selectMedia(item.id)}><span className="media-art">{item.kind === "image" ? <Image src={item.url} alt={item.name} fill sizes="(max-width: 700px) 33vw, 180px" unoptimized /> : <video src={item.url} aria-label={item.name} muted />}<span className={`tile-media-badge ${item.kind === "video" ? "" : "badge-photo"}`}><Icon name={item.kind === "video" ? "play" : "image"} size={13} /></span><span className="tile-checkbox">{active ? "✓" : ""}</span></span><span className="media-file-name">{item.name}</span></button>; })}<label className="add-more-tile"><span><Icon name="plus" size={20} /></span>Add more<input className="file-picker-input" aria-label="Add content" type="file" accept="image/*,video/*" multiple onChange={props.onUploadChange} /></label></div>}<div className="media-footnote"><span className="info-bubble">i</span> Photos and videos will be matched up to your scheduled time slots, in order.</div></section>

    <section className="panel schedule-panel"><div className="panel-heading"><div><div className="step-label"><span>02</span> FIND YOUR RHYTHM</div><h2>Set your schedule</h2><p>One post a day, a few a week — whatever works for you.</p></div><span className="panel-spark">✳</span></div><div className="schedule-fields"><label className="field-wrap"><span>START DATE</span><span className="input-with-icon"><Icon name="calendar" size={16} /><input type="date" value={props.startDate} onChange={(event) => props.setStartDate(event.target.value)} /></span></label><label className="field-wrap"><span>END DATE <em>OPTIONAL</em></span><span className="input-with-icon"><Icon name="calendar" size={16} /><input type="date" value={props.endDate} min={props.startDate} onChange={(event) => props.setEndDate(event.target.value)} /></span></label><label className="field-wrap frequency-field"><span>HOW OFTEN?</span><span className="input-with-icon"><Icon name="clock" size={16} /><select value={props.frequency} onChange={(event) => props.setFrequency(event.target.value)}><option value="daily">Every day · 1 post a day</option><option value="three-weekly">Three times a week · Mon, Wed, Fri</option><option value="custom">Pick my own days</option></select><Icon name="down" size={15} /></span></label><label className="field-wrap"><span>POST AT</span><span className="input-with-icon"><Icon name="clock" size={16} /><input type="time" value={props.time} onChange={(event) => props.setTime(event.target.value)} /></span></label></div>{props.frequency === "custom" && <div className="custom-days"><span>PICK YOUR DAYS</span>{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day, index) => <button key={day} className={props.customDays.includes(index) ? "weekday-selected" : ""} onClick={() => toggleDay(index)}>{day}</button>)}</div>}{!props.endDate && <div className="date-range-hint"><Icon name="clock" size={14} /> No end date? We’ll plan the next 30 days, and use the content you’ve added.</div>}</section>

    <section className="panel account-panel"><div className="panel-heading"><div><div className="step-label"><span>03</span> WHERE IT ALL GOES</div><h2>Choose your channels</h2><p>Your post will show up on every channel you pick.</p></div><span className="account-count">{props.selectedAccounts.length} SELECTED</span></div><div className="account-choices">{props.accounts.slice(0, 3).map((account) => <button key={account.id} aria-pressed={props.selectedAccounts.includes(account.id)} onClick={() => props.toggleAccount(account.id)} className={`account-chip ${props.selectedAccounts.includes(account.id) ? "account-chip-selected" : ""}`}><span className="account-icon" style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</span><span className="account-chip-label"><b>{account.label}</b><small>{account.handle}</small></span><span className="account-check">{props.selectedAccounts.includes(account.id) ? "✓" : ""}</span></button>)}<Link href="/accounts" className="manage-accounts">+ Connect more accounts</Link></div></section></div>

    <aside className="scheduler-preview"><div className="preview-heading"><div><span className="preview-stars">✳</span><h2>Your schedule</h2></div><span className="preview-live"><i /> LIVE PREVIEW</span></div><div className="preview-subheading"><span>YOUR CONTENT, FINDING ITS PLACE</span><span>{props.preview.length} POSTS</span></div><div className="preview-warning">✦ AI caption starter included — give every draft your own finishing touch.</div>{props.blocked && <div className="schedule-warning"><span>⚠</span><div><b>There’s a little overlap.</b><p>One of these channels already has a post planned for the same time. Tweak the time or edit your other schedule.</p></div></div>}{insufficientContent && <div className="schedule-warning shortage-warning"><span>i</span><div><b>Your content will cover part of this schedule.</b><p>There are more time slots than uploaded items. Add more content, or preview a shorter schedule with what you have.</p></div></div>}{props.media.length > 0 && props.preview.length === 0 && <div className="schedule-warning shortage-warning"><span>i</span><div><b>No posting days in this date range.</b><p>Choose at least one posting day and check the start and end dates.</p></div></div>}<div className="post-preview-list">{props.preview.map((post, index) => <article key={post.id} className={`post-preview-card ${props.draggedPost === index ? "post-dragging" : ""}`} draggable onDragStart={(event) => props.onDragStart(event, index)} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }} onDrop={(event) => { event.preventDefault(); if (props.draggedPost !== null && props.draggedPost !== index) props.onMove(props.draggedPost, index); }}><div className="preview-post-top"><span className="drag-grip" title="Drag to change the order">⠿</span><span className="preview-date">{friendlyDate(post.date)} <span>·</span> {post.time}</span><button title="Remove this post" aria-label={`Remove ${post.mediaName}`} className="remove-preview" onClick={() => props.setNotice("To leave out a post, uncheck its content thumbnail above.")}><Icon name="close" size={14} /></button></div><div className="preview-post-media"><div className="preview-thumb">{post.mediaKind === "image" ? <Image src={post.mediaUrl} alt={post.mediaName} fill sizes="120px" unoptimized /> : <video src={post.mediaUrl} muted aria-label={post.mediaName} />}</div><div className="preview-caption-info"><b>{post.mediaName}</b><span><Icon name="spark" size={12} /> AI caption starter</span></div><span className="platform-icons">{post.platform.map((id) => { const account = props.accounts.find((item) => item.id === id); return account ? <i key={id} title={account.label} style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</i> : null; })}</span></div><label className="caption-edit-label" htmlFor={`caption-${post.id}`}>YOUR CAPTION <span>✎ EDIT</span></label><textarea id={`caption-${post.id}`} className="caption-edit" value={post.caption} onChange={(event) => props.onCaptionChange(post.id, event.target.value)} /></article>)}{props.preview.length === 0 && <div className="preview-empty"><span className="preview-empty-icon">✳</span><b>Your posts will pop up here.</b><p>Pick a few photos, videos, or your days to post. There’s no wrong place to start.</p><span className="empty-arrow">↖ start by adding your content</span></div>}</div>{props.preview.length > 0 && <div className="preview-footer"><span>✳ {props.selected.length} {props.selected.length === 1 ? "post" : "posts"} ready to go</span><span className="preview-footer-note">Drag to reorder <span>⠿</span></span></div>}<button className="button button-primary schedule-submit" disabled={!props.preview.length || props.selectedAccounts.length === 0 || props.blocked} onClick={props.onSave}><Icon name="calendar" size={17} /> Schedule {props.preview.length || ""} {props.preview.length === 1 ? "post" : "posts"} <span>↗</span></button><p className="schedule-disclaimer">Take one last look before scheduling. You can always edit your posts later.</p></aside></div></>;
}

function SectionContent({ section, sectionName, posts, media, onUploadChange, onRemoveMedia, accounts, onRemove, onReschedule, setNotice }: {
  section: string; sectionName: string; posts: ScheduledPost[]; media: MediaItem[]; onUploadChange: (event: ChangeEvent<HTMLInputElement>) => void; onRemoveMedia: (id: string) => void; accounts: SocialAccount[]; onRemove: (id: string) => void; onReschedule: (id: string, date: string) => void; setNotice: (value: string) => void;
}) {
  const [selectedMonth, setSelectedMonth] = useState(() => { const now = new Date(); return new Date(now.getFullYear(), now.getMonth(), 1); });
  const [query, setQuery] = useState("");
  const today = todayString();
  const upcoming = posts.filter((post) => post.date >= today).sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
  const monthDays = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth() + 1, 0).getDate();
  const weekdayOffset = (new Date(selectedMonth.getFullYear(), selectedMonth.getMonth(), 1).getDay() + 6) % 7;
  const changeMonth = (amount: number) => setSelectedMonth((current) => new Date(current.getFullYear(), current.getMonth() + amount, 1));
  const filteredPosts = posts.filter((post) => post.mediaName.toLowerCase().includes(query.toLowerCase()));
  const connectedCount = 3;

  const scheduleCalendar = <section className="panel calendar-panel"><div className="calendar-toolbar"><div><span className="calendar-month-label">YOUR MONTH, AT A GLANCE</span><h2>{selectedMonth.toLocaleDateString("en", { month: "long", year: "numeric" })}</h2></div><div className="calendar-toolbar-actions"><button aria-label="Previous month" onClick={() => changeMonth(-1)}>←</button><button onClick={() => setSelectedMonth(new Date())}>Today</button><button aria-label="Next month" onClick={() => changeMonth(1)}>→</button></div></div><div className="month-grid">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <div className="calendar-weekday" key={day}>{day}</div>)}{Array.from({ length: weekdayOffset }, (_, i) => <div key={`blank-${i}`} className="calendar-day calendar-blank" />)}{Array.from({ length: monthDays }, (_, index) => { const date = `${selectedMonth.getFullYear()}-${String(selectedMonth.getMonth() + 1).padStart(2, "0")}-${String(index + 1).padStart(2, "0")}`; const dayPosts = posts.filter((post) => post.date === date); return <div key={date} className={`calendar-day ${today === date ? "calendar-today" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); const postId = event.dataTransfer.getData("text/plain"); if (postId) onReschedule(postId, date); }}><span className="calendar-day-number">{index + 1}</span>{dayPosts.slice(0, 3).map((post) => <button key={post.id} className="calendar-post-chip" draggable onDragStart={(event) => event.dataTransfer.setData("text/plain", post.id)} title={`${post.time} · ${post.mediaName}`} onClick={() => setNotice(`${friendlyDate(post.date)} at ${post.time} — ${post.mediaName}. Posts in this preview are pending.`)}><span>✳</span> {post.mediaName}</button>)}{dayPosts.length > 3 && <span className="more-posts">+{dayPosts.length - 3} more</span>}</div>; })}</div><div className="calendar-legend"><span><i className="legend-dot legend-pending" /> Pending</span><span><i className="legend-dot legend-published" /> Published</span><span><i className="legend-dot legend-failed" /> Failed</span><span className="calendar-legend-note">Drag a scheduled post to another day to reschedule it.</span></div></section>;

  return <><div className="page-heading"><div><div className="eyebrow page-eyebrow"><span className="live-dot" /> A LITTLE LESS TO JUGGLE</div><h1>{section === "dashboard" ? "Your whole week, in sync." : sectionName}</h1><p>{section === "dashboard" ? "A fresh new day, and a little room to plan something lovely." : section === "calendar" ? "Take a look at what's coming up, all in one place." : section === "content" ? "All your lovely content, right where you left it." : section === "accounts" ? "Your channels, side by side and ready to go." : section === "ai-captions" ? "Find the right words for whatever you're sharing." : section === "analytics" ? "A few helpful signals for the stories you share." : section === "team" ? "Good things are even better made together." : "Your workspace, set up just the way you like it."}</p></div><div className="heading-actions">{section === "content" && <label className="button button-white"><Icon name="upload" size={16} /> Add media<input aria-label="Upload images and videos" className="file-picker-input" type="file" accept="image/*,video/*" multiple onChange={onUploadChange} /></label>}<Link className="button button-primary" href="/bulk-schedule"><Icon name="plus" size={16} /> Create a post</Link></div></div>
    {section === "dashboard" && <><div className="overview-welcome"><div className="welcome-orb">✳</div><div><span className="welcome-kicker">MONDAY, OCTOBER 12 <span>·</span> A NEW WEEK BEGINS</span><h2>Good morning, Alex <span>☀</span></h2><p>Big plans or little moments — there&apos;s room for all of it here.</p></div><Link href="/bulk-schedule" className="welcome-link">Plan your week <span>↗</span></Link></div><div className="stats-grid"><article className="stat-card"><div className="stat-label">TOTAL POSTS <span className="stat-icon lavender"><Icon name="calendar" size={17} /></span></div><b>{posts.length + 42}</b><span className="stat-caption">posts in your planner</span><div className="stat-chart"><i /><i /><i /><i /><i /><i /><i /></div></article><article className="stat-card"><div className="stat-label">PUBLISHED <span className="stat-icon green"><span>✓</span></span></div><b>38</b><span className="stat-caption"><span className="stat-up">↗ 12%</span> vs. last month</span><div className="stat-progress"><i /></div></article><article className="stat-card"><div className="stat-label">FAILED <span className="stat-icon rose"><span>!</span></span></div><b>1</b><span className="stat-caption">needs a quick look</span><button className="failed-note" onClick={() => setNotice("This sample post could not publish because no platform authorization is connected to the preview workspace.")}>View details ↗</button></article><article className="stat-card"><div className="stat-label">UP NEXT <span className="stat-icon peach"><Icon name="clock" size={17} /></span></div><b>{upcoming.length || 3}</b><span className="stat-caption">posts ready to go</span><div className="stat-sparkline">⌁</div></article><article className="stat-card"><div className="stat-label">CHANNELS <span className="stat-icon blue"><Icon name="share" size={16} /></span></div><b>3 <span className="stat-suffix">of 5</span></b><span className="stat-caption">your little corner of the internet</span><div className="stat-avatars">{accounts.slice(0, 3).map((item) => <i key={item.id} style={{ "--account-color": item.color } as React.CSSProperties}>{item.icon}</i>)}</div></article></div><div className="overview-grid"><section className="panel upcoming-panel"><div className="section-card-heading"><div><span className="calendar-month-label">THE GOOD THINGS, COMING UP</span><h2>On your calendar <span className="post-count-pill">{upcoming.length}</span></h2></div><Link href="/calendar">See everything <span>↗</span></Link></div>{upcoming.length === 0 ? <div className="upcoming-empty"><div className="empty-sun">✳</div><b>A fresh page, ready for you.</b><p>Your next posts will live here once you&apos;ve planned them.</p><Link className="button button-primary" href="/bulk-schedule">Schedule your first batch <span>↗</span></Link></div> : <div className="upcoming-list">{upcoming.slice(0, 4).map((post) => <UpcomingRow key={post.id} post={post} accounts={accounts} />)}</div>}<Link href="/bulk-schedule" className="today-create"><span className="today-create-icon">＋</span><span><b>There&apos;s always room for one more.</b><small>Add a little something to your schedule.</small></span><span className="create-arrow">↗</span></Link></section><section className="panel overview-side-panel"><div className="section-card-heading"><div><span className="calendar-month-label">YOUR CHANNELS, TOGETHER</span><h2>Connected accounts</h2></div><Link href="/accounts">Manage <span>↗</span></Link></div><div className="connected-list">{accounts.slice(0, connectedCount).map((account) => <div className="connected-row" key={account.id}><span className="account-icon" style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</span><span className="connected-text"><b>{account.label}</b><small>{account.handle}</small></span><span className="connection-state"><i /> Connected</span></div>)}</div><div className="accounts-footnote"><span>✳</span> All connected. Everything is looking good.</div></section></div></>}
    {section === "calendar" && scheduleCalendar}
    {section === "content" && <section className="panel library-panel"><div className="library-toolbar"><div><span className="calendar-month-label">YOUR LITTLE CONTENT CORNER</span><h2>All your content</h2><p>Keep your campaign moments neat, tidy, and right where you need them.</p></div><span className="library-total">{media.length + demoMedia.length} ITEMS</span></div><div className="media-folder-row"><button className="folder-pill folder-selected">✳ All content</button><button className="folder-pill">☼ January campaign <span>8</span></button><button className="folder-pill">✿ Everyday moments <span>12</span></button><button className="folder-add" onClick={() => setNotice("Give your next campaign a name when you're ready to organize your content.")}>＋ New collection</button></div><div className="library-search"><Icon name="search" size={17} /><input placeholder="Find a photo or video..." value={query} onChange={(event) => setQuery(event.target.value)} /><span>⌘ K</span></div><div className="library-grid">{media.map((item) => <article className="library-card" key={item.id}><div className="library-image">{item.kind === "image" ? <Image src={item.url} alt={item.name} fill sizes="(max-width: 700px) 33vw, 180px" unoptimized /> : <video src={item.url} muted aria-label={item.name} />}<span className="library-format">{item.kind === "video" ? "VIDEO" : "PHOTO"}</span><button className="library-delete" aria-label={`Delete ${item.name}`} onClick={() => onRemoveMedia(item.id)}>⋯</button></div><div className="library-card-meta"><b>{item.name}</b><span>Just now · Unfiled</span></div></article>)}{demoMedia.filter((item) => item.name.toLowerCase().includes(query.toLowerCase())).map((item) => <article className="library-card" key={item.name}><div className={`library-image ${item.className}`}><span className="library-art-symbol">{item.label}</span><span className="library-format">{item.type.toUpperCase()}</span><button className="library-delete" aria-label={`Options for ${item.name}`} onClick={() => setNotice("Demo media is here to give you a feel for your content library.")}>⋯</button></div><div className="library-card-meta"><b>{item.name}</b><span>January campaign · Oct 10</span></div></article>)}<label className="library-add-tile"><Icon name="plus" size={22} /><b>Add more content</b><span>Images and videos</span><input className="file-picker-input" aria-label="Add more content" type="file" accept="image/*,video/*" multiple onChange={onUploadChange} /></label></div></section>}
    {section === "accounts" && <section className="panel manage-accounts-panel"><div className="section-card-heading"><div><span className="calendar-month-label">YOUR CORNER OF THE INTERNET</span><h2>Everything, in good company.</h2><p>Your channels stay right here, together.</p></div><button className="button button-outline" onClick={() => setNotice("Social account authorization will be available when platform integrations are connected.")}>＋ Connect an account</button></div><div className="account-manage-grid">{accounts.map((account, index) => <article className="account-manage-card" key={account.id}><span className="account-icon account-icon-large" style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</span><span className="connection-state"><i /> {index < 3 ? "Connected" : "Not connected"}</span><h3>{account.label}</h3><p>{index < 3 ? account.handle : "Your next channel is waiting"}</p><button onClick={() => setNotice(index < 3 ? `${account.label} is connected to your workspace.` : "Social account authorization will be available when platform integrations are connected.")}>{index < 3 ? "Manage connection ↗" : "Connect account ↗"}</button></article>)}</div><div className="integration-note"><span>✳</span><span>Connecting an account needs the platform&apos;s secure sign-in and authorization. We&apos;ll only publish when you say so.</span></div></section>}
    {section === "ai-captions" && <section className="panel ai-demo-panel"><div className="ai-demo-spark">✦</div><span className="calendar-month-label">A LITTLE SPARK FOR YOUR NEXT BIG IDEA</span><h2>Good words start with a good moment.</h2><p>Choose an image from your content library and create a draft you&apos;ll want to put your name on.</p><Link className="button button-primary" href="/bulk-schedule">Start with your content <span>↗</span></Link><div className="ai-suggestion"><span>✦ A CAPTION STARTER</span><p>“Finding joy in the in-between. The light, the quiet, the little things that make a day feel like yours.”</p><small>#LittleMoments　#GoodThings　#EverydayMagic</small></div><span className="ai-note">This is a writing prompt, not a connected generative AI service. Your voice always comes first.</span></section>}
    {section === "analytics" && <div className="analytics-layout"><section className="panel analytics-chart"><div className="section-card-heading"><div><span className="calendar-month-label">LITTLE WINS, ADDING UP</span><h2>The stories you shared</h2><p>Your overview, for the last 30 days.</p></div><span className="analytics-range">Last 30 days⌄</span></div><div className="analytics-number">12,840 <span>↑ 18.6% this month</span></div><div className="chart-area"><div className="chart-y-labels"><span>4k</span><span>3k</span><span>2k</span><span>1k</span><span>0</span></div><div className="chart-lines"><i /><i /><i /><i /><svg viewBox="0 0 600 155" preserveAspectRatio="none"><defs><linearGradient id="reach-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#b39bdb" stopOpacity=".3" /><stop offset="1" stopColor="#b39bdb" stopOpacity="0" /></linearGradient></defs><path d="M0 130 C40 130 35 92 90 106 S142 115 180 83 S236 105 265 73 S320 96 355 57 S415 81 450 51 S506 70 535 35 S573 44 600 15 L600 155 L0 155Z" fill="url(#reach-gradient)" /><path d="M0 130 C40 130 35 92 90 106 S142 115 180 83 S236 105 265 73 S320 96 355 57 S415 81 450 51 S506 70 535 35 S573 44 600 15" fill="none" stroke="#8e71c5" strokeWidth="3" vectorEffect="non-scaling-stroke" /></svg><div className="chart-x-labels"><span>Sep 12</span><span>Sep 18</span><span>Sep 24</span><span>Sep 30</span><span>Oct 6</span><span>Oct 12</span></div></div></div></section><section className="panel best-time-card"><span className="calendar-month-label">A GOOD TIME TO SAY HELLO</span><h2>Your best posting time</h2><div className="best-time-big">9:30 <span>AM</span></div><p>Your audience is most active on Wednesdays. Try sharing a little something around then.</p><div className="best-time-bars">{[30, 48, 65, 38, 88, 50, 32, 68, 42, 90, 57, 36, 66, 45, 72, 40].map((height, i) => <i key={i} style={{ height: `${height}%` }} className={height === 90 ? "bar-highlight" : ""} />)}</div><div className="best-time-days"><span>MON</span><span>TUE</span><span>WED</span><span>THU</span><span>FRI</span><span>SAT</span><span>SUN</span></div></section></div>}
    {section === "team" && <section className="panel team-panel"><div className="section-card-heading"><div><span className="calendar-month-label">GOOD THINGS HAPPEN TOGETHER</span><h2>Your creative circle</h2><p>One lovely little team, making things happen.</p></div><button className="button button-primary" onClick={() => setNotice("Team invitations will be available when team workspaces are connected.")}>＋ Invite someone</button></div><div className="team-table"><div className="team-table-head"><span>YOUR PEOPLE</span><span>ROLE</span><span>STATUS</span></div><div className="team-table-row"><span className="team-member"><i className="user-avatar">AM</i><span><b>Alex Morgan</b><small>alex@goodthings.studio</small></span></span><span><b className="role-pill">Admin</b></span><span className="connection-state"><i /> You’re here</span></div>{[["Jamie Lee", "jamie@goodthings.studio", "Editor", "JL"], ["Riley Park", "riley@goodthings.studio", "Editor", "RP"]].map(([name, email, role, initials]) => <div className="team-table-row" key={email}><span className="team-member"><i className="user-avatar user-avatar-soft">{initials}</i><span><b>{name}</b><small>{email}</small></span></span><span><b className="role-pill">{role}</b></span><span className="connection-state"><i /> Active</span></div>)}</div></section>}
    {section === "settings" && <section className="panel settings-panel"><span className="calendar-month-label">YOUR SPACE, YOUR WAY</span><h2>The little details.</h2><p>Make your workspace feel a little more like you.</p><div className="settings-form"><label><span>YOUR NAME</span><input defaultValue="Alex Morgan" /></label><label><span>EMAIL ADDRESS</span><input type="email" defaultValue="alex@goodthings.studio" /></label><label><span>COMPANY</span><input defaultValue="Good Things Studio" /></label><label><span>TIMEZONE</span><select defaultValue="local"><option value="local">Use my local timezone</option><option>Eastern Time (ET)</option><option>Pacific Time (PT)</option><option>UTC</option></select></label><div className="notification-setting"><div><b>Little reminders, when it matters</b><span>Get a heads-up when your posts are ready or need attention.</span></div><button aria-label="Toggle reminders" className="toggle-switch toggle-on" onClick={(event) => event.currentTarget.classList.toggle("toggle-on")}><i /></button></div><button className="button button-primary settings-save" onClick={() => setNotice("Profile preferences are saved for this preview.")}>Save my changes</button></div></section>}
    {section !== "dashboard" && section !== "calendar" && section !== "content" && section !== "accounts" && section !== "ai-captions" && section !== "analytics" && section !== "team" && section !== "settings" && <><section className="panel upcoming-panel"><div className="section-card-heading"><div><span className="calendar-month-label">THE GOOD THINGS, COMING UP</span><h2>On your calendar <span className="post-count-pill">{upcoming.length}</span></h2></div><Link href="/calendar">See everything <span>↗</span></Link></div>{upcoming.length ? <div className="upcoming-list">{upcoming.map((post) => <UpcomingRow key={post.id} post={post} accounts={accounts} onRemove={() => onRemove(post.id)} />)}</div> : <div className="upcoming-empty"><div className="empty-sun">✳</div><b>A fresh page, ready for you.</b><p>Your next posts will live here once you&apos;ve planned them.</p><Link className="button button-primary" href="/bulk-schedule">Schedule your first batch <span>↗</span></Link></div>}</section><section className="panel schedule-overview-list"><div className="library-toolbar"><div><span className="calendar-month-label">SAVED IN YOUR BROWSER</span><h2>Planned posts</h2></div><span className="library-total">{posts.length} POSTS</span></div><div className="schedule-list-toolbar"><span><Icon name="search" size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a post..." /></span><Link className="button button-outline" href="/bulk-schedule">＋ Plan more posts</Link></div>{filteredPosts.length === 0 ? <div className="upcoming-empty"><b>Nothing queued up just yet.</b><p>Your saved posts are kept on this device, ready when you are.</p></div> : filteredPosts.map((post) => <UpcomingRow key={post.id} post={post} accounts={accounts} onRemove={() => onRemove(post.id)} />)}</section></>}
  </>;
}

function UpcomingRow({ post, accounts, onRemove }: { post: ScheduledPost; accounts: SocialAccount[]; onRemove?: () => void }) {
  const colors = ["tile-sunrise", "tile-market", "tile-studio", "tile-reminder"];
  const platforms = post.platform.map((id) => accounts.find((account) => account.id === id)).filter((account): account is SocialAccount => Boolean(account));
  return <article className="upcoming-row"><div className={`upcoming-thumb ${colors[post.mediaName.length % colors.length]}`}><span>{post.mediaName.toLowerCase().endsWith(".mp4") || post.mediaName.toLowerCase().endsWith(".mov") ? "▶" : "✳"}</span></div><div className="upcoming-date"><b>{friendlyDate(post.date)}</b><small><Icon name="clock" size={12} /> {post.time}</small></div><div className="upcoming-info"><b>{post.mediaName}</b><small>{post.caption.split("\n")[0]}</small></div><div className="upcoming-platforms">{platforms.map((account) => <i key={account.id} style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</i>)}</div><span className="pending-tag"><i /> Pending</span>{onRemove && <button aria-label="Remove post" className="remove-saved-post" title="Remove post" onClick={onRemove}><Icon name="close" size={15} /></button>}</article>;
}
