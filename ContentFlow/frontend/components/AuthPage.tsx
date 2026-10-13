"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import Logo from "./Logo";

type Props = { mode: "login" | "signup" | "forgot-password" | "reset-password" };

const content = {
  login: { eyebrow: "IT'S GOOD TO HAVE YOU BACK", title: "Your socials missed you.", detail: "Sign in to your little corner of the internet." },
  signup: { eyebrow: "A LITTLE SOMETHING TO GET YOU STARTED", title: "Make yourself at home.", detail: "A calmer way to plan, share, and show up." },
  "forgot-password": { eyebrow: "HAPPENS TO THE BEST OF US", title: "Let's get you back in.", detail: "Enter your email and we'll help you find your way back." },
  "reset-password": { eyebrow: "ONE LAST LITTLE STEP", title: "Pick a new password.", detail: "Choose something new and secure for your account." },
};

const apiUrl = (process.env.NEXT_PUBLIC_CONTENT_FLOW_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function getErrorMessage(response: Response) {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
    if (typeof body === "object" && body !== null && "detail" in body && Array.isArray(body.detail)) {
      const firstIssue: unknown = body.detail[0];
      if (typeof firstIssue === "object" && firstIssue !== null && "msg" in firstIssue && typeof firstIssue.msg === "string") {
        return firstIssue.msg;
      }
    }
  } catch (error) {
    console.error("Unable to read the authentication error response.", error);
  }
  return `The server returned an error (${response.status}). Please try again.`;
}

export default function AuthPage({ mode }: Props) {
  const router = useRouter();
  const [notice, setNotice] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isSignUp = mode === "signup";
  const isForgot = mode === "forgot-password";
  const isReset = mode === "reset-password";
  const copy = content[mode];

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isForgot || isReset) {
      setNotice("Secure password recovery needs email delivery to be configured. Contact your workspace administrator for now.");
      return;
    }
    setIsSubmitting(true);
    setNotice("");
    const form = new FormData(event.currentTarget);
    const payload = {
      email: String(form.get("email") ?? "").trim(),
      password: String(form.get("password") ?? ""),
      ...(isSignUp ? {
        full_name: String(form.get("full_name") ?? "").trim(),
        workspace_name: String(form.get("workspace_name") ?? "").trim(),
      } : {}),
    };
    try {
      const response = await fetch(`${apiUrl}/api/auth/${isSignUp ? "register" : "login"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await getErrorMessage(response));
      router.replace("/dashboard");
    } catch (error) {
      console.error("Unable to authenticate with the Content-Flow API.", error);
      setNotice(error instanceof Error
        ? `${error.message}${error instanceof TypeError ? ` Check that the backend is running at ${apiUrl}.` : ""}`
        : "Unable to sign in right now. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return <main className="auth-page"><nav className="marketing-nav"><Logo /><Link className="auth-back-link" href="/">← Back home</Link></nav><section className="auth-shell"><div className="auth-illustration"><div className="auth-orbit auth-orbit-one" /><div className="auth-orbit auth-orbit-two" /><div className="auth-note-card"><span className="auth-note-spark">✳</span><b>A little more room for the good stuff.</b><span>Ideas, all in a row.</span></div><span className="auth-floating-star">✦</span><div className="auth-quote"><span>✦ A SMALL REMINDER</span><p>You don&apos;t have to do it all at once.</p></div></div><div className="auth-form-side"><span className="eyebrow page-eyebrow"><span className="live-dot" /> {copy.eyebrow}</span><h1>{copy.title}</h1><p className="auth-description">{copy.detail}</p><form className="auth-form" onSubmit={handleSubmit}>{isSignUp && <><label><span>YOUR NAME</span><input name="full_name" required maxLength={100} placeholder="Alex Morgan" autoComplete="name" /></label><label><span>WORKSPACE NAME</span><input name="workspace_name" required maxLength={120} placeholder="Good Things Studio" autoComplete="organization" /></label></>}<label><span>EMAIL ADDRESS</span><input name="email" required type="email" maxLength={254} placeholder="you@yourcompany.com" autoComplete="email" /></label>{!isForgot && <label><span>PASSWORD</span><input name="password" required type="password" minLength={isSignUp ? 8 : 1} maxLength={128} placeholder={isReset ? "At least 8 characters" : "Your Content-Flow password"} autoComplete={isSignUp || isReset ? "new-password" : "current-password"} />{isSignUp && <small>Use 8+ characters. This is your Content-Flow password — don&apos;t use your email password.</small>}</label>}{mode === "login" && <Link className="auth-forgot" href="/forgot-password">Forgot password?</Link>}<button className="button button-primary auth-submit" type="submit" disabled={isSubmitting}>{isSubmitting ? "Please wait…" : isSignUp ? "Create my account" : isForgot ? "Send me a reset link" : isReset ? "Save my new password" : "Sign in"} {!isSubmitting && <span>↗</span>}</button></form>{notice && <div className="auth-notice" role="status"><span>✳</span><p>{notice}</p></div>}{isForgot && <Link className="auth-return" href="/login">← Back to sign in</Link>}{!isForgot && !isReset && <p className="auth-switch">{isSignUp ? "Already have an account?" : "New around here?"} <Link href={isSignUp ? "/login" : "/signup"}>{isSignUp ? "Sign in" : "Get started"}</Link></p>}{isReset && <p className="auth-switch">Need to request a reset link? <Link href="/forgot-password">Start here</Link></p>}<p className="auth-fineprint">Your content is yours. Your account should be, too.</p></div></section></main>;
}
