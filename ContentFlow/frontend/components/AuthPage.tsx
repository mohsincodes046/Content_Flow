"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import Logo from "./Logo";

type Props = { mode: "login" | "signup" | "forgot-password" | "reset-password" };

const content = {
  login: { eyebrow: "IT'S GOOD TO HAVE YOU BACK", title: "Your socials missed you.", detail: "Sign in to your little corner of the internet." },
  signup: { eyebrow: "A LITTLE SOMETHING TO GET YOU STARTED", title: "Make yourself at home.", detail: "A calmer way to plan, share, and show up." },
  "forgot-password": { eyebrow: "HAPPENS TO THE BEST OF US", title: "Let's get you back in.", detail: "Enter your email and we'll help you find your way back." },
  "reset-password": { eyebrow: "ONE LAST LITTLE STEP", title: "Pick a new password.", detail: "Choose something new and secure for your account." },
};

export default function AuthPage({ mode }: Props) {
  const [notice, setNotice] = useState("");
  const isSignUp = mode === "signup";
  const isForgot = mode === "forgot-password";
  const isReset = mode === "reset-password";
  const copy = content[mode];

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(
      isForgot ? "Password recovery needs a secure email service to be configured before a reset link can be sent."
        : isReset ? "Password updates need a secure, single-use reset token verified by the server."
          : "Account sign-in and registration need a secure authentication service before accounts can be created."
    );
  }

  return <main className="auth-page"><nav className="marketing-nav"><Logo /><Link className="auth-back-link" href="/">← Back home</Link></nav><section className="auth-shell"><div className="auth-illustration"><div className="auth-orbit auth-orbit-one" /><div className="auth-orbit auth-orbit-two" /><div className="auth-note-card"><span className="auth-note-spark">✳</span><b>A little more room for the good stuff.</b><span>Ideas, all in a row.</span></div><span className="auth-floating-star">✦</span><div className="auth-quote"><span>✦ A SMALL REMINDER</span><p>You don&apos;t have to do it all at once.</p></div></div><div className="auth-form-side"><span className="eyebrow page-eyebrow"><span className="live-dot" /> {copy.eyebrow}</span><h1>{copy.title}</h1><p className="auth-description">{copy.detail}</p><form className="auth-form" onSubmit={handleSubmit}>{isSignUp && <><label><span>YOUR NAME</span><input required placeholder="Alex Morgan" autoComplete="name" /></label><label><span>COMPANY NAME</span><input required placeholder="Good Things Studio" autoComplete="organization" /></label></>}<label><span>EMAIL ADDRESS</span><input required type="email" placeholder="you@yourcompany.com" autoComplete="email" /></label>{!isForgot && <label><span>PASSWORD</span><input required type="password" minLength={8} placeholder={isReset ? "At least 8 characters" : "Your password"} autoComplete={isSignUp || isReset ? "new-password" : "current-password"} />{isSignUp && <small>Use at least 8 characters.</small>}</label>}{mode === "login" && <Link className="auth-forgot" href="/forgot-password">Forgot password?</Link>}<button className="button button-primary auth-submit" type="submit">{isSignUp ? "Create my account" : isForgot ? "Send me a reset link" : isReset ? "Save my new password" : "Sign in"} <span>↗</span></button></form>{notice && <div className="auth-notice" role="status"><span>✳</span><p>{notice}</p></div>}{isForgot && <Link className="auth-return" href="/login">← Back to sign in</Link>}{!isForgot && !isReset && <p className="auth-switch">{isSignUp ? "Already have an account?" : "New around here?"} <Link href={isSignUp ? "/login" : "/signup"}>{isSignUp ? "Sign in" : "Get started"}</Link></p>}{isReset && <p className="auth-switch">Need to request a reset link? <Link href="/forgot-password">Start here</Link></p>}<p className="auth-fineprint">Your content is yours. Your account should be, too.</p></div></section></main>;
}
