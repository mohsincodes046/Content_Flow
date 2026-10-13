import Link from "next/link";
import Logo from "../components/Logo";

const benefits = [
  { icon: "✳", title: "Plan a month in minutes", copy: "Drop in a batch of content and let a flexible schedule do the heavy lifting." },
  { icon: "✦", title: "A little help from AI", copy: "Find the right words and hashtags, then make every caption your own." },
  { icon: "↗", title: "Everything, in one place", copy: "Keep your channels, campaigns, and publishing calendar working together." },
];

export default function Home() {
  return (
    <main className="marketing-page">
      <nav className="marketing-nav">
        <Logo />
        <div className="marketing-nav-links">
          <a href="#features">Features</a>
          <Link className="signin-link" href="/login">Sign in</Link>
          <Link className="button button-primary nav-cta" href="/signup">Get started <span>↗</span></Link>
        </div>
      </nav>

      <section className="marketing-hero">
        <div className="hero-copy">
          <div className="eyebrow"><span className="live-dot" /> YOUR SOCIALS, IN SYNC</div>
          <h1>Make room for<br />the <span>big ideas.</span></h1>
          <p className="hero-description">One calm little corner for all your social channels. Plan it once, show up everywhere.</p>
          <div className="hero-actions">
            <Link className="button button-primary hero-cta" href="/signup">Get started for free <span>↗</span></Link>
            <Link className="hero-secondary" href="/dashboard"><span className="play-icon">▶</span> Take a look around</Link>
          </div>
          <div className="social-proof"><div className="avatar-stack"><span>J</span><span>M</span><span>A</span><span>+</span></div><span>Made for the people behind the posts</span></div>
        </div>

        <div className="hero-art" aria-label="Illustration of the Content-Flow content calendar">
          <div className="art-orb orb-one" /><div className="art-orb orb-two" />
          <div className="floating-note"><span className="note-sparkle">✳</span><span><strong>All caught up!</strong><small>Your next post is on its way</small></span><span className="checkmark">✓</span></div>
          <div className="hero-calendar">
            <div className="mock-top"><div className="mock-brand"><span className="mini-mark">✳</span> your week, at a glance</div><div className="mock-dots"><i /><i /><i /></div></div>
            <div className="mock-calendar-head"><span>Content calendar</span><span className="mock-month">October 2026　⌄</span></div>
            <div className="mock-days">{["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].map((d, i) => <div className="mock-day" key={d}><small>{d}</small><b className={i === 2 ? "today-circle" : ""}>{[12, 13, 14, 15, 16, 17, 18][i]}</b>{i === 0 || i === 2 || i === 4 || i === 6 ? <span className={`mock-post post-${i}`} /> : null}</div>)}</div>
            <div className="mock-posts"><div className="mock-post-card"><span className="mock-image mock-image-one">✿</span><span><small>INSTAGRAM · 9:30 AM</small><b>Little things, big joy ✨</b></span><span className="mock-status">●</span></div><div className="mock-post-card"><span className="mock-image mock-image-two">◉</span><span><small>TIKTOK · 2:00 PM</small><b>A peek behind the scenes...</b></span><span className="mock-status mint">●</span></div></div>
            <div className="mock-bottom"><span>✳  12 posts planned this week</span><span className="mock-progress"><i /></span><b>+4</b></div>
          </div>
          <div className="floating-ai"><span>✦</span><div><small>A LITTLE AI MAGIC</small><b>Caption, coming right up.</b></div><span className="ai-arrow">↗</span></div>
        </div>
      </section>

      <section className="feature-section" id="features">
        <div className="feature-heading"><span className="eyebrow">LESS BUSYWORK, MORE YOU</span><h2>Your whole social world.<br /><span>One easy rhythm.</span></h2></div>
        <div className="feature-cards">{benefits.map((item, i) => <article className="feature-card" key={item.title}><div className={`feature-icon icon-${i}`}>{item.icon}</div><h3>{item.title}</h3><p>{item.copy}</p><Link href="/dashboard">Explore the dashboard <span>↗</span></Link></article>)}</div>
      </section>
      <footer className="marketing-footer"><Logo /><span>Made for what you make. © 2026 Content-Flow</span></footer>
    </main>
  );
}
