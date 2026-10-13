import type { Metadata } from "next";
import { Suspense } from "react";
import DashboardApp from "../../components/DashboardApp";
import AuthPage from "../../components/AuthPage";

type Props = { params: Promise<{ section: string }> };
const authModes = ["login", "signup", "forgot-password", "reset-password"] as const;
const dashboardSections = [
  "dashboard",
  "content",
  "calendar",
  "bulk-schedule",
  "create-post",
  "review-queue",
  "ai-captions",
  "analytics",
  "accounts",
  "team",
  "settings",
] as const;

export function generateStaticParams() {
  return [...dashboardSections, ...authModes].map((section) => ({ section }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { section } = await params;
  if (authModes.includes(section as (typeof authModes)[number])) {
    const authTitles: Record<(typeof authModes)[number], string> = { login: "Sign in", signup: "Get started", "forgot-password": "Forgot password", "reset-password": "Reset password" };
    return { title: authTitles[section as (typeof authModes)[number]] };
  }
  const title = section === "create-post"
    ? "Submit Content"
    : section.split("-").map((word) => word[0]?.toUpperCase() + word.slice(1)).join(" ");
  return { title: title || "Dashboard" };
}

export default function SectionPage({ params }: Props) {
  return <Suspense fallback={null}><SectionPageContent params={params} /></Suspense>;
}

async function SectionPageContent({ params }: Props) {
  const { section } = await params;
  if (authModes.includes(section as (typeof authModes)[number])) return <AuthPage mode={section as (typeof authModes)[number]} />;
  return <DashboardApp section={section} />;
}
