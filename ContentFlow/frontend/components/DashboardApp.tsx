"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type DragEvent, type FormEvent } from "react";
import Logo from "./Logo";
import SubmissionWorkflow from "./SubmissionWorkflow";

type MediaItem = { id: string; name: string; url: string; kind: "image" | "video" };
type ScheduledPost = {
  id: string;
  mediaName: string;
  date: string;
  time: string;
  platform: string[];
  caption: string;
  assetId?: string | null;
  facebookAccountId?: string | null;
  publishStatus: "scheduled" | "publishing" | "published" | "failed";
  publishError?: string | null;
};
type SocialAccount = { id: string; label: string; color: string; icon: string };
type ConnectedSocialAccount = { id: string; account_id: string; platform: string; account_name: string; account_type: string };
type SocialProviderStatus = { provider: string; configured: boolean; accounts: ConnectedSocialAccount[]; publisher_enabled: boolean };
type DashboardUser = { id: string; email: string; full_name: string; workspace_name: string };

const apiUrl = (process.env.NEXT_PUBLIC_CONTENT_FLOW_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const accounts: SocialAccount[] = [
  { id: "instagram", label: "Instagram", color: "#e76072", icon: "◎" },
  { id: "facebook", label: "Facebook", color: "#4d76e9", icon: "f" },
  { id: "tiktok", label: "TikTok", color: "#1c1c20", icon: "♪" },
  { id: "linkedin", label: "LinkedIn", color: "#3285bd", icon: "in" },
  { id: "youtube", label: "YouTube", color: "#e8584d", icon: "▶" },
];

/** Short, truthful status for a channel based on real connections. */
const channelStatus = (platform: string, connected: ConnectedSocialAccount[]) => {
  const names = connected.filter((account) => account.platform === platform).map((account) => account.account_name);
  if (platform === "facebook") {
    return names.length ? `${names.length === 1 ? names[0] : `${names.length} Pages`} · auto-publish` : "Not connected";
  }
  if (platform === "instagram" && names.length) return `${names.length === 1 ? `@${names[0]}` : `${names.length} accounts`} · calendar only`;
  return "Calendar only";
};

const navigation = [
  { label: "Overview", href: "/dashboard", icon: "grid", section: "WORKSPACE" },
  { label: "Content library", href: "/content", icon: "image" },
  { label: "Calendar", href: "/calendar", icon: "calendar" },
  { label: "Bulk schedule", href: "/bulk-schedule", icon: "stack", badge: "CORE" },
  { label: "Submit content", href: "/create-post", icon: "plus" },
  { label: "Review queue", href: "/review-queue", icon: "spark" },
  { label: "AI captions", href: "/ai-captions", icon: "spark" },
  { label: "Analytics", href: "/analytics", icon: "chart", section: "MANAGE" },
  { label: "Social accounts", href: "/accounts", icon: "share" },
  { label: "Team", href: "/team", icon: "users" },
  { label: "Settings", href: "/settings", icon: "settings" },
];

const localDate = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const todayString = () => localDate(new Date());
const supportedPlatforms = new Set(["instagram", "facebook", "linkedin", "youtube", "tiktok"]);
const publishStatusLabel: Record<ScheduledPost["publishStatus"], string> = {
  scheduled: "Scheduled",
  publishing: "Publishing…",
  published: "Published",
  failed: "Failed",
};
const isPublishStatus = (value: unknown): value is ScheduledPost["publishStatus"] =>
  value === "scheduled" || value === "publishing" || value === "published" || value === "failed";
const sortScheduledPosts = (posts: ScheduledPost[]) => [...posts].sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
const parseScheduledPosts = (value: unknown): ScheduledPost[] => {
  if (!Array.isArray(value)) throw new Error("The server returned an invalid schedule.");
  return value.map((item): ScheduledPost => {
    if (
      typeof item !== "object" ||
      item === null ||
      !("id" in item) ||
      typeof item.id !== "string" ||
      !("media_name" in item) ||
      typeof item.media_name !== "string" ||
      !("date" in item) ||
      typeof item.date !== "string" ||
      !("time" in item) ||
      typeof item.time !== "string" ||
      !("caption" in item) ||
      typeof item.caption !== "string" ||
      !("platforms" in item) ||
      !Array.isArray(item.platforms) ||
      !item.platforms.every((platform: unknown) => typeof platform === "string" && supportedPlatforms.has(platform)) ||
      !("publish_status" in item) || !isPublishStatus(item.publish_status) ||
      ("asset_id" in item && typeof item.asset_id !== "string" && item.asset_id !== null) ||
      ("facebook_account_id" in item && typeof item.facebook_account_id !== "string" && item.facebook_account_id !== null) ||
      ("publish_error" in item && typeof item.publish_error !== "string" && item.publish_error !== null)
    ) {
      throw new Error("The server returned an invalid scheduled post.");
    }
    return {
      id: item.id,
      mediaName: item.media_name,
      date: item.date,
      time: item.time,
      platform: item.platforms,
      caption: item.caption,
      assetId: "asset_id" in item && (typeof item.asset_id === "string" || item.asset_id === null) ? item.asset_id : null,
      facebookAccountId: "facebook_account_id" in item && (typeof item.facebook_account_id === "string" || item.facebook_account_id === null) ? item.facebook_account_id : null,
      publishStatus: item.publish_status,
      publishError: "publish_error" in item && (typeof item.publish_error === "string" || item.publish_error === null) ? item.publish_error : null,
    };
  });
};
const parseLegacyScheduledPosts = (saved: string): ScheduledPost[] => {
  const value: unknown = JSON.parse(saved);
  if (!Array.isArray(value)) throw new Error("Older saved schedules have an invalid format.");
  return value.map((item): ScheduledPost => {
    if (
      typeof item !== "object" ||
      item === null ||
      !("id" in item) ||
      typeof item.id !== "string" ||
      !("mediaName" in item) ||
      typeof item.mediaName !== "string" ||
      !("date" in item) ||
      typeof item.date !== "string" ||
      !("time" in item) ||
      typeof item.time !== "string" ||
      !("caption" in item) ||
      typeof item.caption !== "string" ||
      !("platform" in item) ||
      !Array.isArray(item.platform) ||
      !item.platform.every((platform: unknown) => typeof platform === "string" && supportedPlatforms.has(platform))
    ) {
      throw new Error("An older saved schedule has an invalid format.");
    }
    return {
      id: item.id,
      mediaName: item.mediaName,
      date: item.date,
      time: item.time,
      platform: item.platform,
      caption: item.caption,
      publishStatus: "scheduled",
    };
  });
};
const apiErrorMessage = async (response: Response, fallback: string) => {
  const payload: unknown = await response.json().catch(() => null);
  if (typeof payload === "object" && payload !== null && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return `${fallback} (${response.status}).`;
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
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<DashboardUser | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [logoutPending, setLogoutPending] = useState(false);
  const [authError, setAuthError] = useState("");
  const [posts, setPosts] = useState<ScheduledPost[]>([]);
  const [postsLoading, setPostsLoading] = useState(true);
  const [postsLoadError, setPostsLoadError] = useState("");
  const [postsReloadKey, setPostsReloadKey] = useState(0);
  const [scheduleMutationPending, setScheduleMutationPending] = useState(false);
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [mediaUploading, setMediaUploading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [captionEdits, setCaptionEdits] = useState<Record<string, string>>({});
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>(["instagram", "tiktok"]);
  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedSocialAccount[]>([]);
  const [facebookPages, setFacebookPages] = useState<ConnectedSocialAccount[]>([]);
  const [facebookPagesError, setFacebookPagesError] = useState("");
  const [selectedFacebookPageId, setSelectedFacebookPageId] = useState("");
  const [facebookPublisherEnabled, setFacebookPublisherEnabled] = useState(false);
  const [startDate, setStartDate] = useState(todayString);
  const [endDate, setEndDate] = useState("");
  const [frequency, setFrequency] = useState("daily");
  const [customDays, setCustomDays] = useState<number[]>([1, 3, 5]);
  const [time, setTime] = useState("10:00");
  const [notice, setNotice] = useState("");
  const [draggedPost, setDraggedPost] = useState<number | null>(null);
  const [showNotifications, setShowNotifications] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiUrl}/api/auth/me`, { credentials: "include", signal: controller.signal })
      .then(async (response) => {
        if (response.status === 401) {
          router.replace("/login");
          return;
        }
        if (!response.ok) throw new Error(`Account check failed (${response.status}).`);
        const user: unknown = await response.json();
        if (typeof user !== "object" || user === null || !("id" in user) || !("full_name" in user) || !("workspace_name" in user) || !("email" in user)) {
          throw new Error("The server returned an unexpected account response.");
        }
        setCurrentUser({
          id: String(user.id),
          email: String(user.email),
          full_name: String(user.full_name),
          workspace_name: String(user.workspace_name),
        });
        setSessionReady(true);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        console.error("Unable to verify the Content-Flow account session.", error);
        setAuthError(error instanceof Error ? error.message : "Account verification failed.");
        setSessionReady(true);
      });
    return () => controller.abort();
  }, [router]);

  useEffect(() => {
    if (!currentUser) return;
    const controller = new AbortController();
    async function loadFacebookPages() {
      setFacebookPagesError("");
      try {
        const response = await fetch(`${apiUrl}/api/social/providers`, {
          credentials: "include",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(await apiErrorMessage(response, "Unable to load connected Facebook Pages"));
        const result: unknown = await response.json();
        if (!Array.isArray(result)) throw new Error("The server returned an invalid social provider list.");
        const meta = result.find((item): item is SocialProviderStatus =>
          typeof item === "object" && item !== null
          && "provider" in item && item.provider === "meta"
          && "configured" in item && typeof item.configured === "boolean"
          && "publisher_enabled" in item && typeof item.publisher_enabled === "boolean"
          && "accounts" in item && Array.isArray(item.accounts),
        );
        if (!meta) throw new Error("The server did not return Meta connection status.");
        setFacebookPublisherEnabled(meta.publisher_enabled);
        const validAccounts = meta.accounts.filter((account): account is ConnectedSocialAccount =>
          typeof account === "object" && account !== null
          && "id" in account && typeof account.id === "string"
          && "account_id" in account && typeof account.account_id === "string"
          && "platform" in account && typeof account.platform === "string"
          && "account_name" in account && typeof account.account_name === "string"
          && "account_type" in account && typeof account.account_type === "string",
        );
        const pages = validAccounts.filter((account) => account.platform === "facebook");
        setConnectedAccounts(validAccounts);
        setFacebookPages(pages);
        setSelectedFacebookPageId((current) =>
          pages.some((page) => page.id === current) ? current : pages.length === 1 ? pages[0].id : "",
        );
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("Unable to load connected Facebook Pages.", error);
        setFacebookPagesError(error instanceof Error ? error.message : "Unable to load connected Facebook Pages.");
      }
    }
    void loadFacebookPages();
    return () => controller.abort();
  }, [currentUser]);

  useEffect(() => {
    const userId = currentUser?.id;
    if (!userId) return;

    const controller = new AbortController();
    async function loadScheduledPosts() {
      setPostsLoading(true);
      setPostsLoadError("");
      try {
        const response = await fetch(`${apiUrl}/api/scheduled-posts`, {
          credentials: "include",
          signal: controller.signal,
        });
        if (response.status === 401) {
          router.replace("/login");
          throw new Error("Your session has expired. Please sign in again.");
        }
        if (!response.ok) throw new Error(await apiErrorMessage(response, "Unable to load your saved schedule"));
        let loadedPosts = parseScheduledPosts(await response.json());
        setPosts(loadedPosts);

        const legacyKey = `content-flow-posts-${userId}`;
        const legacySnapshot = window.localStorage.getItem(legacyKey);
        if (legacySnapshot) {
          const legacyPosts = parseLegacyScheduledPosts(legacySnapshot);
          for (let offset = 0; offset < legacyPosts.length; offset += 366) {
            const batch = legacyPosts.slice(offset, offset + 366);
            const migrationResponse = await fetch(`${apiUrl}/api/scheduled-posts`, {
              method: "POST",
              credentials: "include",
              signal: controller.signal,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                posts: batch.map(({ mediaName, date, time, platform, caption }) => ({
                  media_name: mediaName,
                  date,
                  time,
                  platforms: platform,
                  caption,
                })),
              }),
            });
            if (!migrationResponse.ok) {
              throw new Error(await apiErrorMessage(migrationResponse, "Unable to move older schedules to your account"));
            }
            const migrated = parseScheduledPosts(await migrationResponse.json());
            loadedPosts = sortScheduledPosts([
              ...loadedPosts,
              ...migrated.filter((post) => !loadedPosts.some((loaded) => loaded.id === post.id)),
            ]);
            setPosts(loadedPosts);
          }
          window.localStorage.removeItem(legacyKey);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("Unable to load or migrate scheduled posts.", error);
        setPostsLoadError(error instanceof Error ? error.message : "Unable to load your saved schedule.");
      } finally {
        if (!controller.signal.aborted) setPostsLoading(false);
      }
    }
    void loadScheduledPosts();
    return () => controller.abort();
  }, [currentUser?.id, postsReloadKey, router]);

  async function handleLogout() {
    if (logoutPending) return;
    setLogoutPending(true);
    try {
      const response = await fetch(`${apiUrl}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) throw new Error(`Sign out failed (${response.status}).`);
      router.replace("/login");
    } catch (error) {
      console.error("Unable to sign out from the Content-Flow API.", error);
      setNotice(error instanceof Error ? error.message : "Unable to sign out. Please try again.");
      setLogoutPending(false);
    }
  }

  const removeMedia = useCallback((id: string) => {
    const item = media.find((entry) => entry.id === id);
    if (item) URL.revokeObjectURL(item.url);
    setMedia((current) => current.filter((entry) => entry.id !== id));
    setSelected((current) => current.filter((entry) => entry !== id));
  }, [media]);

  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    const accepted = Array.from(files).filter((file) => (file.type.startsWith("image/") || file.type.startsWith("video/")) && file.size <= 50 * 1024 * 1024);
    if (accepted.length !== files.length) setNotice("A few files were skipped. Choose image or video files under 50 MB each.");
    if (!accepted.length) return;
    setMediaUploading(true);
    try {
      for (const file of accepted) {
        const formData = new FormData();
        formData.append("file", file);
        const response = await fetch(`${apiUrl}/api/assets`, {
          method: "POST",
          credentials: "include",
          body: formData,
        });
        if (!response.ok) throw new Error(await apiErrorMessage(response, `Unable to upload ${file.name}`));
        const uploaded: unknown = await response.json();
        if (
          typeof uploaded !== "object" || uploaded === null ||
          !("id" in uploaded) || typeof uploaded.id !== "string" ||
          !("filename" in uploaded) || typeof uploaded.filename !== "string"
        ) {
          throw new Error("The server returned an invalid uploaded asset.");
        }
        const item = {
          id: uploaded.id,
          name: uploaded.filename,
          url: URL.createObjectURL(file),
          kind: file.type.startsWith("video/") ? "video" as const : "image" as const,
        };
        setMedia((current) => [...current, item]);
        setSelected((current) => [...current, item.id]);
      }
      if (accepted.length === files.length) setNotice("");
    } catch (error) {
      console.error("Unable to upload content to the Content-Flow API.", error);
      setNotice(error instanceof Error ? error.message : "Unable to upload content. Please try again.");
    } finally {
      setMediaUploading(false);
    }
  }, [setNotice]);

  const onUploadChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files?.length) void uploadFiles(event.target.files);
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
      const id = `${mediaId}-${date}`;
      return { id, mediaId, mediaName: item.name, mediaKind: item.kind, mediaUrl: item.url, date, time, platform: selectedAccounts, caption: captionEdits[id] ?? "" };
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
  async function saveSchedule() {
    if (mediaUploading) {
      setNotice("Wait for the uploads to finish before scheduling.");
      return;
    }
    if (postsLoading || postsLoadError) {
      setNotice(postsLoadError || "Your saved schedule is still loading. Try again in a moment.");
      return;
    }
    if (preview.length === 0 || selectedAccounts.length === 0) {
      setNotice(selectedAccounts.length === 0 ? "Choose at least one social account before scheduling." : "Add some photos or videos first, then your schedule is ready.");
      return;
    }
    if (selectedAccounts.includes("facebook") && !selectedFacebookPageId) {
      setNotice(facebookPages.length
        ? "Choose the Facebook Page that should receive this post."
        : "Connect a Facebook Page first on the Social accounts page.");
      return;
    }
    if (selectedAccounts.includes("facebook") && preview.some((post) => post.mediaKind !== "image")) {
      setNotice("Facebook scheduled publishing currently supports images only. Remove video posts or deselect Facebook.");
      return;
    }
    if (blocked) {
      setNotice("There's already a post planned for one of these accounts at the same time. Change the publishing time or edit your existing schedule.");
      return;
    }
    if (scheduleMutationPending) return;
    setScheduleMutationPending(true);
    try {
      const response = await fetch(`${apiUrl}/api/scheduled-posts`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          posts: preview.map((post) => ({
            media_name: post.mediaName,
            date: post.date,
            time: post.time,
            platforms: post.platform,
            caption: post.caption,
            asset_id: post.mediaId,
            facebook_account_id: post.platform.includes("facebook") ? selectedFacebookPageId : null,
            timezone_offset_minutes: new Date().getTimezoneOffset(),
          })),
        }),
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Unable to save scheduled posts"));
      const savedPosts = parseScheduledPosts(await response.json());
      setPosts((current) => sortScheduledPosts([
        ...current,
        ...savedPosts.filter((saved) => !current.some((post) => post.id === saved.id)),
      ]));
      const includesFacebook = preview.some((post) => post.platform.includes("facebook"));
      setNotice(includesFacebook && facebookPublisherEnabled
        ? `${savedPosts.length} ${savedPosts.length === 1 ? "post is" : "posts are"} scheduled for ${facebookPages.find((page) => page.id === selectedFacebookPageId)?.account_name}. Facebook will publish them at the selected time.`
        : includesFacebook
          ? `${savedPosts.length} post${savedPosts.length === 1 ? "" : "s"} saved to the calendar. Automatic publishing is turned off on this server, so nothing will be posted yet.`
          : `${savedPosts.length} post${savedPosts.length === 1 ? "" : "s"} saved to the calendar. Automatic publishing is currently implemented for Facebook Page image posts only.`);
    } catch (error) {
      console.error("Unable to save scheduled posts.", error);
      setNotice(error instanceof Error ? error.message : "Your schedule couldn't be saved. Please try again.");
    } finally {
      setScheduleMutationPending(false);
    }
  }

  async function removePost(id: string) {
    if (scheduleMutationPending) return;
    setScheduleMutationPending(true);
    try {
      const response = await fetch(`${apiUrl}/api/scheduled-posts/${encodeURIComponent(id)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Unable to remove the scheduled post"));
      setPosts((current) => current.filter((post) => post.id !== id));
      setNotice("Post removed from your schedule.");
    } catch (error) {
      console.error("Unable to update saved schedules.", error);
      setNotice(error instanceof Error ? error.message : "Unable to remove the post. Please try again.");
    } finally {
      setScheduleMutationPending(false);
    }
  }

  async function reschedulePost(id: string, date: string) {
    const movingPost = posts.find((post) => post.id === id);
    if (!movingPost || movingPost.date === date || scheduleMutationPending) return;
    const collision = posts.some((post) => post.id !== id && post.date === date && post.time === movingPost.time && post.platform.some((platform) => movingPost.platform.includes(platform)));
    if (collision) {
      setNotice("There’s already a post planned for one of these channels at that time. Try another date.");
      return;
    }
    setScheduleMutationPending(true);
    try {
      const response = await fetch(`${apiUrl}/api/scheduled-posts/${encodeURIComponent(id)}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date }),
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Unable to change the scheduled date"));
      const updatedPost = parseScheduledPosts([await response.json()])[0];
      setPosts((current) => sortScheduledPosts(current.map((post) => post.id === id ? updatedPost : post)));
      setNotice(`Post moved to ${friendlyDate(date)}.`);
    } catch (error) {
      console.error("Unable to update the scheduled date.", error);
      setNotice(error instanceof Error ? error.message : "Unable to change the scheduled date. Please try again.");
    } finally {
      setScheduleMutationPending(false);
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

  const initials = currentUser?.full_name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") ?? "";
  const workspaceName = currentUser?.workspace_name ?? "Content-Flow";
  const failedPosts = posts.filter((post) => post.publishStatus === "failed");
  const navContent = <><div className="sidebar-brand"><Logo href="/dashboard" /><button aria-label="Close navigation" className="mobile-close" onClick={() => setMobileOpen(false)}><Icon name="close" /></button></div><div className="workspace-switch"><div className="workspace-avatar">{workspaceName[0]?.toUpperCase()}</div><div><b>{workspaceName}</b><small>Workspace owner</small></div></div><nav className="side-nav">{navigation.map((item) => <div key={item.href}>{item.section && <div className="nav-section-label">{item.section}</div>}<Link href={item.href} onClick={() => setMobileOpen(false)} className={`nav-item ${section === item.href.slice(1) || (section === "create-post" && item.href === "/bulk-schedule") ? "nav-active" : ""}`}><Icon name={item.icon} /><span>{item.label}</span>{item.badge && <span className="nav-badge">{item.badge}</span>}</Link></div>)}</nav><div className="sidebar-bottom"><button type="button" className="user-profile" onClick={handleLogout} disabled={logoutPending} aria-label="Sign out of Content-Flow"><div className="user-avatar">{initials}</div><span><b>{currentUser?.full_name}</b><small>{logoutPending ? "Signing out…" : "Sign out"}</small></span><Icon name="more" /></button></div></>;

  if (!sessionReady) {
    return <main className="auth-check-screen"><Logo /><p>Checking your secure session…</p></main>;
  }
  if (!currentUser) {
    return <main className="auth-check-screen"><Logo /><h1>Dashboard sign-in required</h1><p>{authError || "Sign in to continue to your workspace."}</p><Link className="button button-primary" href="/login">Sign in</Link></main>;
  }

  return <div className="app-layout"><div className={`sidebar-backdrop ${mobileOpen ? "backdrop-visible" : ""}`} onClick={() => setMobileOpen(false)} /><aside className={`app-sidebar ${mobileOpen ? "sidebar-open" : ""}`}>{navContent}</aside><main className="dashboard-main"><header className="topbar"><div className="topbar-left"><button aria-label="Open navigation" className="mobile-menu-button" onClick={() => setMobileOpen(true)}><Icon name="menu" /></button><div className="breadcrumb"><span>{workspaceName}</span><span className="crumb-separator">/</span><b>{title}</b></div></div><div className="topbar-right"><div className="notification-wrap"><button aria-label={failedPosts.length ? `Notifications: ${failedPosts.length} failed ${failedPosts.length === 1 ? "post" : "posts"}` : "Notifications"} className={`icon-button notification-button ${showNotifications ? "icon-selected" : ""}`} onClick={() => setShowNotifications(!showNotifications)}><Icon name="bell" />{failedPosts.length > 0 && <i />}</button>{showNotifications && <div className="notification-popover">{failedPosts.length ? <><b>{failedPosts.length} {failedPosts.length === 1 ? "post" : "posts"} could not publish</b>{failedPosts.slice(0, 3).map((post) => <p key={post.id}><strong>{friendlyDate(post.date)} · {post.mediaName}</strong><br />{post.publishError ?? "Publishing failed."}</p>)}</> : <><b>You’re all caught up</b><p>Publishing problems will show up here.</p></>}<Link href="/calendar" onClick={() => setShowNotifications(false)}>See your calendar <span>↗</span></Link></div>}</div><span className="topbar-divider" /><button type="button" className="topbar-avatar" onClick={handleLogout} aria-label="Sign out of Content-Flow">{initials}</button></div></header><div className="page-content">{postsLoading && <p className="schedule-state" role="status">Loading your saved schedule…</p>}{postsLoadError && <div className="schedule-load-error" role="alert"><span>{postsLoadError}</span><button type="button" onClick={() => setPostsReloadKey((current) => current + 1)}>Try again</button></div>}{section === "create-post" || section === "review-queue" ? <SubmissionWorkflow view={section === "create-post" ? "submit" : "review"} setNotice={setNotice} /> : section === "bulk-schedule" ? <BulkSchedule section={section} media={media} selected={selected} setSelected={setSelected} onFilesDrop={uploadFiles} onUploadChange={onUploadChange} mediaUploading={mediaUploading} startDate={startDate} setStartDate={setStartDate} endDate={endDate} setEndDate={setEndDate} frequency={frequency} setFrequency={setFrequency} customDays={customDays} setCustomDays={setCustomDays} time={time} setTime={setTime} accounts={accounts} connectedAccounts={connectedAccounts} selectedAccounts={selectedAccounts} toggleAccount={toggleAccount} facebookPages={facebookPages} facebookPagesError={facebookPagesError} facebookPublisherEnabled={facebookPublisherEnabled} selectedFacebookPageId={selectedFacebookPageId} setSelectedFacebookPageId={setSelectedFacebookPageId} preview={preview} expectedCount={expectedCount} onSave={saveSchedule} saveDisabled={postsLoading || Boolean(postsLoadError) || scheduleMutationPending || mediaUploading} saving={scheduleMutationPending} onMove={movePost} onRemovePreview={(id) => setSelected((current) => current.filter((item) => item !== id))} onCaptionChange={updateCaption} onDragStart={handleDragStart} draggedPost={draggedPost} blocked={blocked} setNotice={setNotice} /> : <SectionContent section={section} sectionName={sectionName} currentUser={currentUser} connectedAccounts={connectedAccounts} posts={posts} media={media} onUploadChange={onUploadChange} onRemoveMedia={removeMedia} accounts={accounts} onRemove={removePost} onReschedule={reschedulePost} setNotice={setNotice} />}<div className={`toast-notice ${notice ? "toast-show" : ""}`} role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")}><Icon name="close" size={15} /></button></div><footer className="app-footer"><span>Made for what you make. <span className="footer-spark">✳</span></span></footer></div></main></div>;
}

type BulkProps = {
  section: string; media: MediaItem[]; selected: string[]; setSelected: React.Dispatch<React.SetStateAction<string[]>>; onFilesDrop: (files: FileList | File[]) => Promise<void>; onUploadChange: (event: ChangeEvent<HTMLInputElement>) => void; mediaUploading: boolean;
  startDate: string; setStartDate: (value: string) => void; endDate: string; setEndDate: (value: string) => void; frequency: string; setFrequency: (value: string) => void; customDays: number[]; setCustomDays: React.Dispatch<React.SetStateAction<number[]>>; time: string; setTime: (value: string) => void;
  accounts: SocialAccount[]; connectedAccounts: ConnectedSocialAccount[]; selectedAccounts: string[]; toggleAccount: (id: string) => void; facebookPages: ConnectedSocialAccount[]; facebookPagesError: string; facebookPublisherEnabled: boolean; selectedFacebookPageId: string; setSelectedFacebookPageId: (id: string) => void; preview: Array<{ id: string; mediaId: string; mediaName: string; mediaKind: "image" | "video"; mediaUrl: string; date: string; time: string; platform: string[]; caption: string }>;
  expectedCount: number; onSave: () => void; saveDisabled: boolean; saving: boolean; onMove: (source: number, target: number) => void; onRemovePreview: (mediaId: string) => void; onCaptionChange: (id: string, caption: string) => void; onDragStart: (event: DragEvent<HTMLElement>, index: number) => void; draggedPost: number | null; blocked: boolean; setNotice: (value: string) => void;
};

function BulkSchedule(props: BulkProps) {
  const [view, setView] = useState<"all" | "images" | "videos">("all");
  const visibleMedia = props.media.filter((item) => view === "all" || item.kind === (view === "images" ? "image" : "video"));
  const selectMedia = (id: string) => props.setSelected((current) => current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id]);
  const toggleDay = (day: number) => props.setCustomDays((current) => current.includes(day) ? current.filter((item) => item !== day) : [...current, day].sort());
  const insufficientContent = props.selected.length > 0 && props.preview.length < props.expectedCount;

  return <><div className="page-heading"><div><div className="eyebrow page-eyebrow"><span className="live-dot" /> YOUR NEW FAVOURITE SHORTCUT</div><h1>{props.section === "create-post" ? "Create a post" : "A month of posts. Sorted."}</h1><p>Line up your content, pick your pace, and let your calendar fall into place.</p></div><div className="heading-actions"><Link href="/calendar" className="button button-white"><Icon name="calendar" size={17} /> Open calendar</Link></div></div>
    <div className="bulk-banner"><div className="banner-sticker">✳</div><div><b>Big batch of content? You’re in the right place.</b><span>Everything below is just a preview — nothing gets scheduled until you say so.</span></div><div className="banner-spark">✦</div></div>
    <div className="scheduler-layout"><div className="scheduler-primary"><section className="panel media-panel"><div className="panel-heading"><div><div className="step-label"><span>01</span> FIRST THINGS FIRST</div><h2>Pick your content</h2><p>Bring a little inspiration from your library.</p></div><label className="button button-outline upload-button"><Icon name="upload" size={16} /> {props.mediaUploading ? "Uploading…" : "Upload content"}<input aria-label="Upload images and videos" className="file-picker-input" type="file" accept="image/*,video/*" multiple onChange={props.onUploadChange} hidden /></label></div><div className="media-filter">{(["all", "images", "videos"] as const).map((item) => <button key={item} className={`filter-pill ${view === item ? "filter-active" : ""}`} onClick={() => setView(item)}>{item === "all" ? "Everything" : item === "images" ? "Photos" : "Videos"}</button>)}<span className="media-count">{props.media.length} items <span>·</span> {props.selected.length} selected</span></div>{visibleMedia.length === 0 ? <label className="upload-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (event.dataTransfer.files.length) void props.onFilesDrop(event.dataTransfer.files); }}><div className="drop-icon"><Icon name="upload" size={23} /></div><b>Your next great post starts here.</b><span>Drop your photos and videos here, or browse your files.</span><span className="drop-formats">PNG, JPG, WEBP, GIF, MP4, MOV · up to 50 MB each</span></label> : <div className="media-grid">{visibleMedia.map((item) => { const active = props.selected.includes(item.id); return <button aria-label={`${active ? "Deselect" : "Select"} ${item.name}`} key={item.id} className={`media-tile ${active ? "media-selected" : ""}`} onClick={() => selectMedia(item.id)}><span className="media-art">{item.kind === "image" ? <Image src={item.url} alt={item.name} fill sizes="(max-width: 700px) 33vw, 180px" unoptimized /> : <video src={item.url} aria-label={item.name} muted />}<span className={`tile-media-badge ${item.kind === "video" ? "" : "badge-photo"}`}><Icon name={item.kind === "video" ? "play" : "image"} size={13} /></span><span className="tile-checkbox">{active ? "✓" : ""}</span></span><span className="media-file-name">{item.name}</span></button>; })}<label className="add-more-tile"><span><Icon name="plus" size={20} /></span>Add more<input className="file-picker-input" aria-label="Add content" type="file" accept="image/*,video/*" multiple onChange={props.onUploadChange} /></label></div>}<div className="media-footnote"><span className="info-bubble">i</span> {props.mediaUploading ? "Uploading content to your workspace…" : "Uploaded photos and videos will be matched to their scheduled time slots, in order."}</div></section>

    <section className="panel schedule-panel"><div className="panel-heading"><div><div className="step-label"><span>02</span> FIND YOUR RHYTHM</div><h2>Set your schedule</h2><p>One post a day, a few a week — whatever works for you.</p></div><span className="panel-spark">✳</span></div><div className="schedule-fields"><label className="field-wrap"><span>START DATE</span><span className="input-with-icon"><Icon name="calendar" size={16} /><input type="date" value={props.startDate} onChange={(event) => props.setStartDate(event.target.value)} /></span></label><label className="field-wrap"><span>END DATE <em>OPTIONAL</em></span><span className="input-with-icon"><Icon name="calendar" size={16} /><input type="date" value={props.endDate} min={props.startDate} onChange={(event) => props.setEndDate(event.target.value)} /></span></label><label className="field-wrap frequency-field"><span>HOW OFTEN?</span><span className="input-with-icon"><Icon name="clock" size={16} /><select value={props.frequency} onChange={(event) => props.setFrequency(event.target.value)}><option value="daily">Every day · 1 post a day</option><option value="three-weekly">Three times a week · Mon, Wed, Fri</option><option value="custom">Pick my own days</option></select><Icon name="down" size={15} /></span></label><label className="field-wrap"><span>POST AT</span><span className="input-with-icon"><Icon name="clock" size={16} /><input type="time" value={props.time} onChange={(event) => props.setTime(event.target.value)} /></span></label></div>{props.frequency === "custom" && <div className="custom-days"><span>PICK YOUR DAYS</span>{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day, index) => <button key={day} className={props.customDays.includes(index) ? "weekday-selected" : ""} onClick={() => toggleDay(index)}>{day}</button>)}</div>}{!props.endDate && <div className="date-range-hint"><Icon name="clock" size={14} /> No end date? We’ll plan the next 30 days, and use the content you’ve added.</div>}</section>

    <section className="panel account-panel"><div className="panel-heading"><div><div className="step-label"><span>03</span> WHERE IT ALL GOES</div><h2>Choose your channels</h2><p>Your post will show up on every channel you pick.</p></div><span className="account-count">{props.selectedAccounts.length} SELECTED</span></div><div className="account-choices">{props.accounts.map((account) => <button key={account.id} aria-pressed={props.selectedAccounts.includes(account.id)} onClick={() => props.toggleAccount(account.id)} className={`account-chip ${props.selectedAccounts.includes(account.id) ? "account-chip-selected" : ""}`}><span className="account-icon" style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</span><span className="account-chip-label"><b>{account.label}</b><small>{channelStatus(account.id, props.connectedAccounts)}</small></span><span className="account-check">{props.selectedAccounts.includes(account.id) ? "✓" : ""}</span></button>)}<Link href="/accounts" className="manage-accounts">Manage connections ↗</Link></div>{props.selectedAccounts.includes("facebook") && <div className="facebook-page-picker"><label className="field-wrap"><span>POST THIS TO FACEBOOK PAGE</span><span className="input-with-icon"><Icon name="share" size={15} /><select value={props.selectedFacebookPageId} onChange={(event) => props.setSelectedFacebookPageId(event.target.value)}><option value="">Choose a connected Page</option>{props.facebookPages.map((page) => <option key={page.id} value={page.id}>{page.account_name}</option>)}</select><Icon name="down" size={15} /></span></label>{props.facebookPagesError ? <p className="facebook-page-help" role="alert">{props.facebookPagesError}</p> : props.facebookPages.length === 0 ? <p className="facebook-page-help">No connected Facebook Pages found. Connect a Page in <Link href="/accounts">Social accounts</Link> first.</p> : <p className="facebook-page-help">{props.facebookPublisherEnabled ? "Uploaded images will publish to this Page at the scheduled time." : "Choose the Page. Automatic publishing is turned off on this server, so posts are saved to the calendar only."} Facebook scheduling currently supports images.</p>}</div>}</section></div>

    <aside className="scheduler-preview"><div className="preview-heading"><div><span className="preview-stars">✳</span><h2>Your schedule</h2></div><span className="preview-live"><i /> LIVE PREVIEW</span></div><div className="preview-subheading"><span>YOUR CONTENT, FINDING ITS PLACE</span><span>{props.preview.length} POSTS</span></div><div className="preview-warning">✦ Need caption ideas? <Link href="/ai-captions">Generate platform-specific drafts</Link>, then paste them below.</div>{props.blocked && <div className="schedule-warning"><span>⚠</span><div><b>There’s a little overlap.</b><p>One of these channels already has a post planned for the same time. Tweak the time or edit your other schedule.</p></div></div>}{insufficientContent && <div className="schedule-warning shortage-warning"><span>i</span><div><b>Your content will cover part of this schedule.</b><p>There are more time slots than uploaded items. Add more content, or preview a shorter schedule with what you have.</p></div></div>}{props.media.length > 0 && props.preview.length === 0 && <div className="schedule-warning shortage-warning"><span>i</span><div><b>No posting days in this date range.</b><p>Choose at least one posting day and check the start and end dates.</p></div></div>}<div className="post-preview-list">{props.preview.map((post, index) => <article key={post.id} className={`post-preview-card ${props.draggedPost === index ? "post-dragging" : ""}`} draggable onDragStart={(event) => props.onDragStart(event, index)} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }} onDrop={(event) => { event.preventDefault(); if (props.draggedPost !== null && props.draggedPost !== index) props.onMove(props.draggedPost, index); }}><div className="preview-post-top"><span className="drag-grip" title="Drag to change the order">⠿</span><span className="preview-date">{friendlyDate(post.date)} <span>·</span> {post.time}</span><button title="Remove this post" aria-label={`Remove ${post.mediaName}`} className="remove-preview" onClick={() => props.setNotice("To leave out a post, uncheck its content thumbnail above.")}><Icon name="close" size={14} /></button></div><div className="preview-post-media"><div className="preview-thumb">{post.mediaKind === "image" ? <Image src={post.mediaUrl} alt={post.mediaName} fill sizes="120px" unoptimized /> : <video src={post.mediaUrl} muted aria-label={post.mediaName} />}</div><div className="preview-caption-info"><b>{post.mediaName}</b><span>{post.mediaKind === "video" ? "Video" : "Photo"}</span></div><span className="platform-icons">{post.platform.map((id) => { const account = props.accounts.find((item) => item.id === id); return account ? <i key={id} title={account.label} style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</i> : null; })}</span></div><label className="caption-edit-label" htmlFor={`caption-${post.id}`}>YOUR CAPTION <span>✎ EDIT</span></label><textarea id={`caption-${post.id}`} className="caption-edit" placeholder="Write a caption for this post…" maxLength={5000} value={post.caption} onChange={(event) => props.onCaptionChange(post.id, event.target.value)} /></article>)}{props.preview.length === 0 && <div className="preview-empty"><span className="preview-empty-icon">✳</span><b>Your posts will pop up here.</b><p>Pick a few photos, videos, or your days to post. There’s no wrong place to start.</p><span className="empty-arrow">↖ start by adding your content</span></div>}</div>{props.preview.length > 0 && <div className="preview-footer"><span>✳ {props.selected.length} {props.selected.length === 1 ? "post" : "posts"} ready to go</span><span className="preview-footer-note">Drag to reorder <span>⠿</span></span></div>}<button className="button button-primary schedule-submit" disabled={!props.preview.length || props.selectedAccounts.length === 0 || props.blocked || props.saveDisabled} onClick={props.onSave}><Icon name="calendar" size={17} /> {props.saving ? "Saving…" : <>Schedule {props.preview.length || ""} {props.preview.length === 1 ? "post" : "posts"} <span>↗</span></>}</button><p className="schedule-disclaimer">Take one last look before scheduling. You can always edit your posts later.</p></aside></div></>;
}

function SectionContent({ section, sectionName, currentUser, connectedAccounts, posts, media, onUploadChange, onRemoveMedia, accounts, onRemove, onReschedule, setNotice }: {
  section: string; sectionName: string; currentUser: DashboardUser; connectedAccounts: ConnectedSocialAccount[]; posts: ScheduledPost[]; media: MediaItem[]; onUploadChange: (event: ChangeEvent<HTMLInputElement>) => void; onRemoveMedia: (id: string) => void; accounts: SocialAccount[]; onRemove: (id: string) => void; onReschedule: (id: string, date: string) => void; setNotice: (value: string) => void;
}) {
  const [selectedMonth, setSelectedMonth] = useState(() => { const now = new Date(); return new Date(now.getFullYear(), now.getMonth(), 1); });
  const [query, setQuery] = useState("");
  const [captionTopic, setCaptionTopic] = useState("");
  const [captionAudience, setCaptionAudience] = useState("");
  const [captionInstructions, setCaptionInstructions] = useState("");
  const [captionLanguage, setCaptionLanguage] = useState("English");
  const [captionPlatforms, setCaptionPlatforms] = useState<string[]>(["instagram", "linkedin"]);
  const [captionDrafts, setCaptionDrafts] = useState<Array<{ platform: string; caption: string; hashtags: string[] }>>([]);
  const [captionPending, setCaptionPending] = useState(false);
  const [captionError, setCaptionError] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordChangePending, setPasswordChangePending] = useState(false);
  const [passwordChangeMessage, setPasswordChangeMessage] = useState("");
  const [passwordChangeError, setPasswordChangeError] = useState(false);
  const today = todayString();
  const upcoming = posts.filter((post) => post.date >= today && post.publishStatus === "scheduled").sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
  const statusCounts = { scheduled: 0, publishing: 0, published: 0, failed: 0 };
  for (const post of posts) statusCounts[post.publishStatus] += 1;
  const connectedPlatforms = accounts.filter((account) => connectedAccounts.some((connected) => connected.platform === account.id));
  const now = new Date();
  const greeting = now.getHours() < 12 ? "Good morning" : now.getHours() < 18 ? "Good afternoon" : "Good evening";
  const firstName = currentUser.full_name.split(/\s+/)[0] ?? "";
  const todayLabel = now.toLocaleDateString("en", { weekday: "long", month: "long", day: "numeric" }).toUpperCase();
  const initialsOf = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
  const monthDays = new Date(selectedMonth.getFullYear(), selectedMonth.getMonth() + 1, 0).getDate();

  function toggleCaptionPlatform(platform: string) {
    setCaptionPlatforms((current) => current.includes(platform)
      ? current.filter((item) => item !== platform)
      : [...current, platform]);
  }

  async function generateCaptions(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCaptionError("");
    setCaptionDrafts([]);
    if (captionPlatforms.length === 0) {
      setCaptionError("Choose at least one platform.");
      return;
    }
    setCaptionPending(true);
    try {
      const response = await fetch(`${apiUrl}/api/ai/captions`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: captionTopic,
          audience: captionAudience,
          instructions: captionInstructions,
          language: captionLanguage,
          platforms: captionPlatforms,
        }),
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Caption generation failed"));
      const result: unknown = await response.json();
      if (typeof result !== "object" || result === null || !("posts" in result) || !Array.isArray(result.posts)) {
        throw new Error("The AI service returned an unexpected response.");
      }
      const drafts = result.posts.filter((draft): draft is { platform: string; caption: string; hashtags: string[] } =>
        typeof draft === "object" && draft !== null
        && "platform" in draft && typeof draft.platform === "string"
        && "caption" in draft && typeof draft.caption === "string"
        && "hashtags" in draft && Array.isArray(draft.hashtags)
        && draft.hashtags.every((tag: unknown) => typeof tag === "string"),
      );
      if (drafts.length !== result.posts.length || drafts.length !== captionPlatforms.length) {
        throw new Error("The AI service did not return one valid caption for each platform.");
      }
      setCaptionDrafts(drafts);
    } catch (error) {
      setCaptionError(error instanceof Error ? error.message : "Caption generation failed. Please try again.");
    } finally {
      setCaptionPending(false);
    }
  }
  const weekdayOffset = (new Date(selectedMonth.getFullYear(), selectedMonth.getMonth(), 1).getDay() + 6) % 7;
  const changeMonth = (amount: number) => setSelectedMonth((current) => new Date(current.getFullYear(), current.getMonth() + amount, 1));
  const filteredPosts = posts.filter((post) => post.mediaName.toLowerCase().includes(query.toLowerCase()));
  const filteredMedia = media.filter((item) => item.name.toLowerCase().includes(query.toLowerCase()));
  const handlePasswordChange = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPasswordChangeMessage("");
    setPasswordChangeError(false);
    if (newPassword !== confirmPassword) {
      setPasswordChangeError(true);
      setPasswordChangeMessage("The new password and confirmation do not match.");
      return;
    }

    setPasswordChangePending(true);
    try {
      const response = await fetch(`${apiUrl}/api/auth/change-password`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!response.ok) {
        const errorPayload: unknown = await response.json().catch(() => null);
        const detail =
          typeof errorPayload === "object" &&
          errorPayload !== null &&
          "detail" in errorPayload &&
          typeof errorPayload.detail === "string"
            ? errorPayload.detail
            : "Could not change your password. Please try again.";
        throw new Error(detail);
      }

      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordChangeMessage("Your Content-Flow password has been updated. Other signed-in sessions have been logged out.");
    } catch (error) {
      setPasswordChangeError(true);
      setPasswordChangeMessage(error instanceof Error ? error.message : "Could not change your password. Please try again.");
    } finally {
      setPasswordChangePending(false);
    }
  };

  const scheduleCalendar = <section className="panel calendar-panel"><div className="calendar-toolbar"><div><span className="calendar-month-label">YOUR MONTH, AT A GLANCE</span><h2>{selectedMonth.toLocaleDateString("en", { month: "long", year: "numeric" })}</h2></div><div className="calendar-toolbar-actions"><button aria-label="Previous month" onClick={() => changeMonth(-1)}>←</button><button onClick={() => setSelectedMonth(new Date())}>Today</button><button aria-label="Next month" onClick={() => changeMonth(1)}>→</button></div></div><div className="month-grid">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <div className="calendar-weekday" key={day}>{day}</div>)}{Array.from({ length: weekdayOffset }, (_, i) => <div key={`blank-${i}`} className="calendar-day calendar-blank" />)}{Array.from({ length: monthDays }, (_, index) => { const date = `${selectedMonth.getFullYear()}-${String(selectedMonth.getMonth() + 1).padStart(2, "0")}-${String(index + 1).padStart(2, "0")}`; const dayPosts = posts.filter((post) => post.date === date); return <div key={date} className={`calendar-day ${today === date ? "calendar-today" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); const postId = event.dataTransfer.getData("text/plain"); if (postId) onReschedule(postId, date); }}><span className="calendar-day-number">{index + 1}</span>{dayPosts.slice(0, 3).map((post) => <button key={post.id} className={`calendar-post-chip chip-${post.publishStatus}`} draggable={post.publishStatus === "scheduled"} onDragStart={(event) => event.dataTransfer.setData("text/plain", post.id)} title={`${post.time} · ${post.mediaName} · ${publishStatusLabel[post.publishStatus]}`} onClick={() => setNotice(`${friendlyDate(post.date)} at ${post.time} — ${post.mediaName}. Status: ${publishStatusLabel[post.publishStatus]}.${post.publishError ? ` ${post.publishError}` : ""}`)}><span>✳</span> {post.mediaName}</button>)}{dayPosts.length > 3 && <span className="more-posts">+{dayPosts.length - 3} more</span>}</div>; })}</div><div className="calendar-legend"><span><i className="legend-dot legend-pending" /> Pending</span><span><i className="legend-dot legend-published" /> Published</span><span><i className="legend-dot legend-failed" /> Failed</span><span className="calendar-legend-note">Drag a scheduled post to another day to reschedule it.</span></div></section>;

  return <><div className="page-heading"><div><div className="eyebrow page-eyebrow"><span className="live-dot" /> A LITTLE LESS TO JUGGLE</div><h1>{section === "dashboard" ? "Your whole week, in sync." : sectionName}</h1><p>{section === "dashboard" ? "A fresh new day, and a little room to plan something lovely." : section === "calendar" ? "Take a look at what's coming up, all in one place." : section === "content" ? "Upload the photos and videos you want to post." : section === "accounts" ? "Your channels, side by side and ready to go." : section === "ai-captions" ? "Find the right words for whatever you're sharing." : section === "analytics" ? "A few helpful signals for the stories you share." : section === "team" ? "Good things are even better made together." : "Your workspace, set up just the way you like it."}</p></div><div className="heading-actions">{section === "content" && <label className="button button-white"><Icon name="upload" size={16} /> Add media<input aria-label="Upload images and videos" className="file-picker-input" type="file" accept="image/*,video/*" multiple onChange={onUploadChange} /></label>}<Link className="button button-primary" href="/bulk-schedule"><Icon name="plus" size={16} /> Create a post</Link></div></div>
    {section === "dashboard" && <><div className="overview-welcome"><div className="welcome-orb">✳</div><div><span className="welcome-kicker">{todayLabel}</span><h2>{greeting}{firstName ? `, ${firstName}` : ""}</h2><p>Big plans or little moments — there&apos;s room for all of it here.</p></div><Link href="/bulk-schedule" className="welcome-link">Plan your week <span>↗</span></Link></div><div className="stats-grid"><article className="stat-card"><div className="stat-label">TOTAL POSTS <span className="stat-icon lavender"><Icon name="calendar" size={17} /></span></div><b>{posts.length}</b><span className="stat-caption">posts in your planner</span></article><article className="stat-card"><div className="stat-label">PUBLISHED <span className="stat-icon green"><span>✓</span></span></div><b>{statusCounts.published}</b><span className="stat-caption">sent to a connected account</span></article><article className="stat-card"><div className="stat-label">FAILED <span className="stat-icon rose"><span>!</span></span></div><b>{statusCounts.failed}</b><span className="stat-caption">{statusCounts.failed ? "needs a quick look" : "nothing needs attention"}</span>{statusCounts.failed > 0 && <Link className="failed-note" href="/calendar">View in calendar ↗</Link>}</article><article className="stat-card"><div className="stat-label">UP NEXT <span className="stat-icon peach"><Icon name="clock" size={17} /></span></div><b>{upcoming.length}</b><span className="stat-caption">scheduled from today on</span></article><article className="stat-card"><div className="stat-label">CHANNELS <span className="stat-icon blue"><Icon name="share" size={16} /></span></div><b>{connectedPlatforms.length} <span className="stat-suffix">of {accounts.length}</span></b><span className="stat-caption">channels connected</span><div className="stat-avatars">{connectedPlatforms.map((item) => <i key={item.id} style={{ "--account-color": item.color } as React.CSSProperties}>{item.icon}</i>)}</div></article></div><div className="overview-grid"><section className="panel upcoming-panel"><div className="section-card-heading"><div><span className="calendar-month-label">THE GOOD THINGS, COMING UP</span><h2>On your calendar <span className="post-count-pill">{upcoming.length}</span></h2></div><Link href="/calendar">See everything <span>↗</span></Link></div>{upcoming.length === 0 ? <div className="upcoming-empty"><div className="empty-sun">✳</div><b>A fresh page, ready for you.</b><p>Your next posts will live here once you&apos;ve planned them.</p><Link className="button button-primary" href="/bulk-schedule">Schedule your first batch <span>↗</span></Link></div> : <div className="upcoming-list">{upcoming.slice(0, 4).map((post) => <UpcomingRow key={post.id} post={post} accounts={accounts} />)}</div>}<Link href="/bulk-schedule" className="today-create"><span className="today-create-icon">＋</span><span><b>There&apos;s always room for one more.</b><small>Add a little something to your schedule.</small></span><span className="create-arrow">↗</span></Link></section><section className="panel overview-side-panel"><div className="section-card-heading"><div><span className="calendar-month-label">YOUR CHANNELS, TOGETHER</span><h2>Connected accounts</h2></div><Link href="/accounts">Manage <span>↗</span></Link></div>{connectedAccounts.length === 0 ? <div className="upcoming-empty"><b>No accounts connected yet.</b><p>Connect a Facebook Page to publish scheduled posts automatically.</p><Link className="button button-primary" href="/accounts">Connect an account <span>↗</span></Link></div> : <div className="connected-list">{connectedAccounts.map((connected) => { const account = accounts.find((item) => item.id === connected.platform); return <div className="connected-row" key={connected.id}><span className="account-icon" style={{ "--account-color": account?.color } as React.CSSProperties}>{account?.icon ?? "•"}</span><span className="connected-text"><b>{connected.account_name}</b><small>{account?.label ?? connected.platform} · {connected.account_type}</small></span><span className="connection-state"><i /> Connected</span></div>; })}</div>}</section></div></>}
    {section === "calendar" && scheduleCalendar}
    {section === "content" && <section className="panel library-panel"><div className="library-toolbar"><div><span className="calendar-month-label">YOUR LITTLE CONTENT CORNER</span><h2>All your content</h2><p>Keep your campaign moments neat, tidy, and right where you need them.</p></div><span className="library-total">{media.length} {media.length === 1 ? "ITEM" : "ITEMS"}</span></div><p className="library-session-note">Files you upload are stored securely in your workspace. This list currently shows uploads from this browser session.</p><div className="library-search"><Icon name="search" size={17} /><input placeholder="Find a photo or video..." value={query} onChange={(event) => setQuery(event.target.value)} /></div><div className="library-grid">{filteredMedia.map((item) => <article className="library-card" key={item.id}><div className="library-image">{item.kind === "image" ? <Image src={item.url} alt={item.name} fill sizes="(max-width: 700px) 33vw, 180px" unoptimized /> : <video src={item.url} muted aria-label={item.name} />}<span className="library-format">{item.kind === "video" ? "VIDEO" : "PHOTO"}</span><button className="library-delete" aria-label={`Hide ${item.name} from this list`} title="Hide from this list" onClick={() => onRemoveMedia(item.id)}>⋯</button></div><div className="library-card-meta"><b>{item.name}</b><span>Uploaded this session</span></div></article>)}<label className="library-add-tile"><Icon name="plus" size={22} /><b>Add more content</b><span>Images and videos</span><input className="file-picker-input" aria-label="Add more content" type="file" accept="image/*,video/*" multiple onChange={onUploadChange} /></label></div></section>}
    {section === "accounts" && <SocialAccountsSection setNotice={setNotice} />}
    {section === "ai-captions" && <section className="panel ai-demo-panel"><div className="ai-demo-spark">✦</div><span className="calendar-month-label">PLATFORM-SPECIFIC DRAFTS</span><h2>Generate captions and hashtags</h2><p>Each selected channel gets its own draft. Review every detail before using it.</p><form className="ai-generator-form" onSubmit={generateCaptions}><label><span>WHAT IS THE POST ABOUT?</span><textarea required maxLength={500} value={captionTopic} onChange={(event) => setCaptionTopic(event.target.value)} placeholder="Describe the announcement, product, event, or story." /></label><label><span>WHO IS IT FOR?</span><input required maxLength={300} value={captionAudience} onChange={(event) => setCaptionAudience(event.target.value)} placeholder="e.g. university students" /></label><label><span>LANGUAGE</span><select value={captionLanguage} onChange={(event) => setCaptionLanguage(event.target.value)}><option>English</option><option>Urdu</option><option>English and Urdu</option></select></label><label><span>FACTS AND BRAND NOTES</span><textarea maxLength={2000} value={captionInstructions} onChange={(event) => setCaptionInstructions(event.target.value)} placeholder="Verified details, tone, required wording, or anything the AI must not assume." /></label><fieldset><legend>PLATFORMS</legend><div className="ai-platform-choices">{accounts.map((account) => <label key={account.id}><input type="checkbox" checked={captionPlatforms.includes(account.id)} onChange={() => toggleCaptionPlatform(account.id)} /><span className="account-icon" style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</span>{account.label}</label>)}</div></fieldset><button className="button button-primary" type="submit" disabled={captionPending}>{captionPending ? "Generating drafts…" : "Generate drafts"}</button></form>{captionError && <p className="ai-generator-error" role="alert">{captionError}</p>}{captionDrafts.length > 0 && <div className="ai-generated-list" aria-live="polite">{captionDrafts.map((draft) => { const account = accounts.find((item) => item.id === draft.platform); const hashtags = draft.hashtags.map((tag) => `#${tag.replace(/^#/, "")}`).join(" "); return <article className="ai-generated-draft" key={draft.platform}><div><span>{account?.label ?? draft.platform}</span><button type="button" onClick={() => navigator.clipboard.writeText(`${draft.caption}\n\n${hashtags}`).then(() => setNotice(`${account?.label ?? "Caption"} draft copied.`)).catch(() => setNotice("Clipboard access is unavailable in this browser."))}>Copy</button></div><p>{draft.caption}</p>{hashtags && <small>{hashtags}</small>}</article>; })}</div>}<span className="ai-note">Generated drafts are suggestions. Verify all facts and platform rules before publishing.</span></section>}
    {section === "analytics" && <div className="analytics-layout"><section className="panel analytics-chart"><div className="section-card-heading"><div><span className="calendar-month-label">PUBLISHING SUMMARY</span><h2>Your posts by status</h2><p>Counts from every post scheduled in this workspace.</p></div></div><div className="analytics-status-grid">{(["scheduled", "publishing", "published", "failed"] as const).map((key) => <div key={key} className={`analytics-status analytics-${key}`}><b>{statusCounts[key]}</b><span>{publishStatusLabel[key]}</span></div>)}</div><div className="analytics-platform-list"><span className="calendar-month-label">POSTS PER CHANNEL</span>{accounts.map((account) => <div key={account.id} className="analytics-platform-row"><span className="account-icon" style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</span><span>{account.label}</span><b>{posts.filter((post) => post.platform.includes(account.id)).length}</b></div>)}</div></section><section className="panel best-time-card"><span className="calendar-month-label">PLATFORM INSIGHTS</span><h2>Reach and engagement</h2><p>Reach, impressions and engagement will appear here once platform insights are connected. Nothing on this page is estimated.</p><Link className="button button-outline" href="/accounts">Review connected accounts ↗</Link></section></div>}
    {section === "team" && <section className="panel team-panel"><div className="section-card-heading"><div><span className="calendar-month-label">GOOD THINGS HAPPEN TOGETHER</span><h2>Your team</h2><p>People who can work in {currentUser.workspace_name}.</p></div><button className="button button-primary" disabled title="Invitations arrive with workspace roles">＋ Invite someone</button></div><div className="team-table"><div className="team-table-head"><span>YOUR PEOPLE</span><span>ROLE</span><span>STATUS</span></div><div className="team-table-row"><span className="team-member"><i className="user-avatar">{initialsOf(currentUser.full_name)}</i><span><b>{currentUser.full_name}</b><small>{currentUser.email}</small></span></span><span><b className="role-pill">Owner</b></span><span className="connection-state"><i /> You</span></div></div><p className="team-coming-soon">Inviting teammates and clients with editor, admin and approver roles is coming soon.</p></section>}
    {section === "settings" && <section className="panel settings-panel"><span className="calendar-month-label">ACCOUNT SECURITY</span><h2>Change your password</h2><p>This updates your Content-Flow password only. It does not change your email account password.</p><form className="settings-form password-change-form" onSubmit={handlePasswordChange}><label><span>CURRENT CONTENT-FLOW PASSWORD</span><input type="password" autoComplete="current-password" required maxLength={128} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label><label><span>NEW PASSWORD</span><input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /><small>Use at least 8 characters.</small></label><label><span>CONFIRM NEW PASSWORD</span><input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label><button className="button button-primary settings-save" type="submit" disabled={passwordChangePending}>{passwordChangePending ? "Updating..." : "Update password"}</button>{passwordChangeMessage && <p className={`password-change-message ${passwordChangeError ? "password-change-error" : "password-change-success"}`} role={passwordChangeError ? "alert" : "status"}>{passwordChangeMessage}</p>}</form></section>}
    {section !== "dashboard" && section !== "calendar" && section !== "content" && section !== "accounts" && section !== "ai-captions" && section !== "analytics" && section !== "team" && section !== "settings" && <><section className="panel upcoming-panel"><div className="section-card-heading"><div><span className="calendar-month-label">THE GOOD THINGS, COMING UP</span><h2>On your calendar <span className="post-count-pill">{upcoming.length}</span></h2></div><Link href="/calendar">See everything <span>↗</span></Link></div>{upcoming.length ? <div className="upcoming-list">{upcoming.map((post) => <UpcomingRow key={post.id} post={post} accounts={accounts} onRemove={() => onRemove(post.id)} />)}</div> : <div className="upcoming-empty"><div className="empty-sun">✳</div><b>A fresh page, ready for you.</b><p>Your next posts will live here once you&apos;ve planned them.</p><Link className="button button-primary" href="/bulk-schedule">Schedule your first batch <span>↗</span></Link></div>}</section><section className="panel schedule-overview-list"><div className="library-toolbar"><div><span className="calendar-month-label">SAVED TO YOUR WORKSPACE</span><h2>Planned posts</h2></div><span className="library-total">{posts.length} POSTS</span></div><div className="schedule-list-toolbar"><span><Icon name="search" size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a post..." /></span><Link className="button button-outline" href="/bulk-schedule">＋ Plan more posts</Link></div>{filteredPosts.length === 0 ? <div className="upcoming-empty"><b>Nothing queued up just yet.</b><p>Posts you schedule are saved to your workspace and will appear here.</p></div> : filteredPosts.map((post) => <UpcomingRow key={post.id} post={post} accounts={accounts} onRemove={() => onRemove(post.id)} />)}</section></>}
  </>;
}

function SocialAccountsSection({ setNotice }: { setNotice: (notice: string) => void }) {
  const [providerStatus, setProviderStatus] = useState<SocialProviderStatus | null>(null);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [accountsError, setAccountsError] = useState("");
  const [disconnectingId, setDisconnectingId] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams(window.location.search);
    const oauthResult = query.get("social");
    if (oauthResult) {
      const messages: Record<string, string> = {
        connected: "Meta connected. Authorized Facebook Pages and linked Instagram professional accounts are listed below.",
        invalid_state: "The Meta sign-in could not be verified. Please connect again.",
        cancelled: "Meta sign-in was cancelled.",
        no_accounts: "Meta authorized successfully, but no Facebook Pages or linked Instagram professional accounts were found.",
        connect_failed: "Meta could not connect. Check your app permissions and try again.",
      };
      setNotice(messages[oauthResult] ?? "Meta sign-in did not complete.");
      query.delete("social");
      const cleanUrl = `${window.location.pathname}${query.toString() ? `?${query}` : ""}${window.location.hash}`;
      window.history.replaceState(window.history.state, "", cleanUrl);
    }

    async function loadMetaAccounts() {
      setAccountsLoading(true);
      setAccountsError("");
      try {
        const response = await fetch(`${apiUrl}/api/social/providers`, {
          credentials: "include",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(await apiErrorMessage(response, "Unable to load social account connections"));
        const result: unknown = await response.json();
        if (!Array.isArray(result)) throw new Error("The server returned an invalid social provider list.");
        const meta = result.find((item): item is SocialProviderStatus =>
          typeof item === "object" && item !== null
          && "provider" in item && item.provider === "meta"
          && "configured" in item && typeof item.configured === "boolean"
          && "publisher_enabled" in item && typeof item.publisher_enabled === "boolean"
          && "accounts" in item && Array.isArray(item.accounts),
        );
        if (!meta) throw new Error("The server did not return Meta connection status.");
        const connectedAccounts = meta.accounts.filter((item): item is ConnectedSocialAccount =>
          typeof item === "object" && item !== null
          && "id" in item && typeof item.id === "string"
          && "account_id" in item && typeof item.account_id === "string"
          && "platform" in item && typeof item.platform === "string"
          && "account_name" in item && typeof item.account_name === "string"
          && "account_type" in item && typeof item.account_type === "string",
        );
        if (connectedAccounts.length !== meta.accounts.length) {
          throw new Error("The server returned an invalid Meta account.");
        }
        setProviderStatus({ ...meta, accounts: connectedAccounts });
      } catch (error) {
        if (controller.signal.aborted) return;
        setAccountsError(error instanceof Error ? error.message : "Could not load connected accounts.");
      } finally {
        if (!controller.signal.aborted) setAccountsLoading(false);
      }
    }

    void loadMetaAccounts();
    return () => controller.abort();
  }, [setNotice]);

  function connectMeta() {
    setNotice("Facebook and Instagram connections are not set up on this server yet. Ask your Content-Flow administrator to configure Meta sign-in.");
  }

  function metaConnectControl(label: string) {
    if (providerStatus?.configured) {
      return <a className="button button-outline" href={`${apiUrl}/api/social/oauth/meta/start`}>{label}</a>;
    }
    return <button className="button button-outline" onClick={connectMeta}>{label}</button>;
  }

  async function disconnectMetaAccount(accountId: string, accountName: string) {
    setDisconnectingId(accountId);
    try {
      const response = await fetch(`${apiUrl}/api/social/accounts/${encodeURIComponent(accountId)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Unable to disconnect this account"));
      setProviderStatus((current) => current
        ? { ...current, accounts: current.accounts.filter((account) => account.id !== accountId) }
        : current);
      setNotice(`${accountName} disconnected from this workspace.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Unable to disconnect this account.");
    } finally {
      setDisconnectingId("");
    }
  }

  return <section className="panel manage-accounts-panel">
    <div className="section-card-heading">
      <div><span className="calendar-month-label">SOCIAL CONNECTIONS</span><h2>Your authorized accounts</h2><p>Connect Facebook Pages and their linked Instagram professional accounts through Meta sign-in.</p></div>
      {metaConnectControl("＋ Connect Meta account")}
    </div>
    {accountsError && <p className="schedule-load-error" role="alert">{accountsError}</p>}
    <div className="account-manage-grid">{accounts.map((account) => {
      const metaPlatform = account.id === "facebook" || account.id === "instagram";
      const connectedAccounts = providerStatus?.accounts.filter((connected) => connected.platform === account.id) ?? [];
      const connected = connectedAccounts.length > 0;
      return <article className="account-manage-card" key={account.id}>
        <span className="account-icon account-icon-large" style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</span>
        <span className={`connection-state ${connected ? "social-connected" : "social-not-connected"}`}><i />{accountsLoading ? "Checking" : connected ? "Connected" : "Not connected"}</span>
        <h3>{account.label}</h3>
        {connected ? connectedAccounts.map((connectedAccount) => <div className="social-connected-account" key={connectedAccount.id}>
          <p>{connectedAccount.account_name} · {connectedAccount.account_type}</p>
          <button type="button" disabled={disconnectingId === connectedAccount.id} onClick={() => void disconnectMetaAccount(connectedAccount.id, connectedAccount.account_name)}>{disconnectingId === connectedAccount.id ? "Disconnecting…" : "Disconnect"}</button>
        </div>) : <p>{accountsLoading ? "Loading authorization status…" : metaPlatform ? "Connect through Meta OAuth" : "Not included in this Meta-only setup"}</p>}
        {metaPlatform
          ? metaConnectControl(connected ? "Connect another Meta account ↗" : "Connect with Meta ↗")
          : <button type="button" disabled title="This platform is outside the current Meta-only integration">Available in a later integration</button>}
      </article>;
    })}</div>
    <div className="integration-note"><span>✳</span><span>Meta sign-in can discover Pages available to you and Instagram professional accounts linked to those Pages. Scheduled image posts can be published automatically to a connected Facebook Page. Instagram publishing is not available yet.</span></div>
  </section>;
}

function UpcomingRow({ post, accounts, onRemove }: { post: ScheduledPost; accounts: SocialAccount[]; onRemove?: () => void }) {
  const colors = ["tile-sunrise", "tile-market", "tile-studio", "tile-reminder"];
  const platforms = post.platform.map((id) => accounts.find((account) => account.id === id)).filter((account): account is SocialAccount => Boolean(account));
  return <article className="upcoming-row"><div className={`upcoming-thumb ${colors[post.mediaName.length % colors.length]}`}><span>{post.mediaName.toLowerCase().endsWith(".mp4") || post.mediaName.toLowerCase().endsWith(".mov") ? "▶" : "✳"}</span></div><div className="upcoming-date"><b>{friendlyDate(post.date)}</b><small><Icon name="clock" size={12} /> {post.time}</small></div><div className="upcoming-info"><b>{post.mediaName}</b><small>{post.caption.split("\n")[0]}</small></div><div className="upcoming-platforms">{platforms.map((account) => <i key={account.id} style={{ "--account-color": account.color } as React.CSSProperties}>{account.icon}</i>)}</div><span className={`pending-tag status-${post.publishStatus}`} title={post.publishError ?? undefined}><i /> {publishStatusLabel[post.publishStatus]}</span>{post.publishStatus === "failed" && post.publishError && <small className="publish-error-text" role="note">{post.publishError}</small>}{onRemove && <button aria-label="Remove post" className="remove-saved-post" title="Remove post" onClick={onRemove}><Icon name="close" size={15} /></button>}</article>;
}
