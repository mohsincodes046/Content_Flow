import type { Metadata } from "next";
import { Suspense } from "react";
import InvitePage from "../../components/InvitePage";

export const metadata: Metadata = { title: "Join a workspace" };

export default function Page() {
  return <Suspense fallback={null}><InvitePage /></Suspense>;
}
