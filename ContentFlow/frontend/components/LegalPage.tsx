import Link from "next/link";
import type { ReactNode } from "react";
import Logo from "./Logo";

// Owner: replace before submitting to Meta App Review.
export const LEGAL_CONTACT = {
  company: "Content Flow",
  email: "[your support email]",
  updated: "16 November 2026",
};

export default function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return <main className="legal-page">
    <nav className="legal-nav"><Logo /><span><Link href="/privacy">Privacy</Link> · <Link href="/terms">Terms</Link> · <Link href="/data-deletion">Data deletion</Link></span></nav>
    <article>
      <h1>{title}</h1>
      <p className="legal-updated">Last updated: {LEGAL_CONTACT.updated}</p>
      {children}
      <p>Questions: contact {LEGAL_CONTACT.company} at {LEGAL_CONTACT.email}.</p>
    </article>
  </main>;
}
