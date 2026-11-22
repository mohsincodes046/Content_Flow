"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, apiErrorMessage, uploadAsset } from "../lib/api";

/** Hands text to the post composer, where it stays editable before anything is published. */
export const AI_DRAFT_KEY = "contentflow.aiDraft";

type Platform = "instagram" | "facebook" | "linkedin" | "tiktok";
type Tone = "friendly" | "professional" | "playful" | "inspirational" | "informative" | "urgent";
type Length = "short" | "medium" | "long";
type Tool = "captions" | "ideas" | "rewrite" | "repurpose" | "hashtags" | "call_to_action" | "description" | "image";
type Result = { key: string; label: string; title?: string; text: string; hashtags: string[] };
type Usage = { used_last_24h: number; daily_limit: number; remaining: number; image_generation_enabled: boolean;
  images_used_last_24h: number; image_daily_limit: number };

const PLATFORMS: Array<{ id: Platform; label: string }> = [
  { id: "instagram", label: "Instagram" }, { id: "facebook", label: "Facebook" },
  { id: "linkedin", label: "LinkedIn" }, { id: "tiktok", label: "TikTok" },
];
const TONES: Tone[] = ["friendly", "professional", "playful", "inspirational", "informative", "urgent"];
const TOOLS: Array<{ id: Tool; label: string; input: string; placeholder: string; hint: string }> = [
  { id: "captions", label: "Captions", input: "WHAT IS THE POST ABOUT?", placeholder: "Describe the announcement, product, event, or story.", hint: "Platform-specific captions with hashtags and a call to action, in up to three variations." },
  { id: "ideas", label: "Content ideas", input: "TOPIC OR GOAL", placeholder: "e.g. a bakery's weekend specials", hint: "Fresh post ideas, each matched to the platform it suits best." },
  { id: "rewrite", label: "Rewrite", input: "CONTENT TO REWRITE", placeholder: "Paste a caption or text.", hint: "The same message in a new tone or length. Facts stay unchanged." },
  { id: "repurpose", label: "Repurpose", input: "SOURCE CONTENT", placeholder: "Paste a blog post, newsletter, video script, or another post.", hint: "One ready-to-post version for each selected platform." },
  { id: "hashtags", label: "Hashtags", input: "WHAT IS THE POST ABOUT?", placeholder: "Paste the caption or describe the post.", hint: "Hashtag sets sized for each platform." },
  { id: "call_to_action", label: "Call to action", input: "WHAT IS THE POST ABOUT?", placeholder: "Paste the caption or describe the post.", hint: "Short, honest calls to action. No invented offers or deadlines." },
  { id: "description", label: "Description", input: "WHAT DOES THE POST OR VIDEO SHOW?", placeholder: "Describe the image or video.", hint: "Searchable post or video descriptions for each platform." },
  { id: "image", label: "Image", input: "DESCRIBE THE IMAGE", placeholder: "e.g. a bright flat-lay of croissants and coffee on a marble table, morning light", hint: "Generate an image and save it to your content library." },
];
const platformLabel = (id?: string | null) => PLATFORMS.find((p) => p.id === id)?.label ?? id ?? "";
const withHashtags = (r: Result) => r.hashtags.length ? `${r.text}\n\n${r.hashtags.map((t) => `#${t.replace(/^#/, "")}`).join(" ")}` : r.text;

export default function AIStudio({ setNotice }: { setNotice: (value: string) => void }) {
  const router = useRouter();
  const [tool, setTool] = useState<Tool>("captions");
  const [text, setText] = useState("");
  const [audience, setAudience] = useState("");
  const [facts, setFacts] = useState("");
  const [language, setLanguage] = useState("English");
  const [platforms, setPlatforms] = useState<Platform[]>(["instagram", "facebook"]);
  const [tone, setTone] = useState<Tone>("friendly");
  const [length, setLength] = useState<Length>("medium");
  const [variations, setVariations] = useState(1);
  const [count, setCount] = useState(3);
  const [cta, setCta] = useState(true);
  const [aspect, setAspect] = useState("1:1");
  const [results, setResults] = useState<Result[]>([]);
  const [image, setImage] = useState<{ url: string; file: File } | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [pending, setPending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const loadUsage = useCallback(() => {
    api<Usage>("/api/ai/usage").then(setUsage).catch(() => undefined);
  }, []);
  useEffect(loadUsage, [loadUsage]);
  useEffect(() => () => { if (image) URL.revokeObjectURL(image.url); }, [image]);

  const current = TOOLS.find((t) => t.id === tool) ?? TOOLS[0];
  const togglePlatform = (id: Platform) => setPlatforms((list) => list.includes(id) ? list.filter((p) => p !== id) : [...list, id]);
  const switchTool = (id: Tool) => { setTool(id); setResults([]); setError(""); };

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    if (tool !== "image" && !platforms.length) { setError("Choose at least one platform."); return; }
    setPending(true);
    setError("");
    try {
      if (tool === "image") {
        const made = await api<{ media_type: string; data_base64: string }>("/api/ai/image", { method: "POST", json: { prompt: text, aspect_ratio: aspect } }, "Image generation failed");
        const bytes = Uint8Array.from(atob(made.data_base64), (c) => c.charCodeAt(0));
        const extension = made.media_type.split("/")[1]?.replace("jpeg", "jpg") ?? "png";
        const file = new File([bytes], `ai-image-${Date.now()}.${extension}`, { type: made.media_type });
        setImage({ url: URL.createObjectURL(file), file });
      } else if (tool === "captions") {
        const made = await api<{ posts: Array<{ platform: string; caption: string; hashtags: string[]; call_to_action: string; variant: number }> }>("/api/ai/captions", {
          method: "POST",
          json: { topic: text, audience: audience || "Our followers", instructions: facts, language, platforms, tone, length, variations, include_call_to_action: cta },
        }, "Caption generation failed");
        setResults(made.posts.map((p) => ({ key: `${p.platform}-${p.variant}`, label: `${platformLabel(p.platform)}${variations > 1 ? ` · Variation ${p.variant}` : ""}`, text: p.caption, hashtags: p.hashtags })));
      } else {
        const made = await api<{ items: Array<{ platform?: string | null; title: string; text: string; hashtags: string[] }> }>("/api/ai/assist", {
          method: "POST",
          json: { task: tool, text, audience, platforms, tone, length, language, count },
        }, "Generation failed");
        setResults(made.items.map((item, index) => ({ key: `${index}`, label: item.platform ? platformLabel(item.platform) : `Option ${index + 1}`, title: item.title, text: item.text, hashtags: item.hashtags })));
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Generation failed.");
    } finally {
      setPending(false);
      loadUsage();
    }
  }

  const edit = (key: string, value: string) => setResults((list) => list.map((r) => r.key === key ? { ...r, text: value } : r));
  const copy = (r: Result) => navigator.clipboard.writeText(withHashtags(r)).then(() => setNotice("Copied.")).catch(() => setNotice("Clipboard access is unavailable in this browser."));
  const sendToComposer = (r: Result) => {
    try { window.sessionStorage.setItem(AI_DRAFT_KEY, withHashtags(r)); } catch { setNotice("Your browser blocked saving the draft. Copy it instead."); return; }
    router.push("/compose");
  };

  async function saveImage() {
    if (!image || saving) return;
    setSaving(true);
    try {
      const response = await uploadAsset(image.file);
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not save the image."));
      setNotice("Image saved to your content library.");
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "Could not save the image.");
    } finally {
      setSaving(false);
    }
  }

  const imageOff = tool === "image" && usage !== null && !usage.image_generation_enabled;
  const usesTone = tool !== "image" && tool !== "hashtags";
  const usesCount = tool === "ideas" || tool === "rewrite" || tool === "call_to_action";

  return <section className="panel ai-demo-panel ai-studio">
    <div className="ai-demo-spark">✦</div>
    <span className="calendar-month-label">AI CONTENT STUDIO</span>
    <h2>Create, rewrite and repurpose</h2>
    <p>{current.hint} Everything is a draft you can edit before it is published.</p>
    {usage && <small className="ai-usage">{usage.remaining} of {usage.daily_limit} text generations left today{usage.image_generation_enabled ? ` · ${Math.max(0, usage.image_daily_limit - usage.images_used_last_24h)} of ${usage.image_daily_limit} images` : ""}</small>}
    <div className="media-filter ai-tool-tabs" role="tablist">{TOOLS.map((t) => <button key={t.id} type="button" role="tab" aria-selected={tool === t.id} className={`filter-pill ${tool === t.id ? "filter-active" : ""}`} onClick={() => switchTool(t.id)}>{t.label}</button>)}</div>

    {imageOff ? <p className="ai-generator-error">AI image generation is not set up on this server yet. An administrator can turn it on with CONTENT_FLOW_AI_IMAGE_MODEL (a Gemini image model) and GEMINI_API_KEY.</p>
      : <form className="ai-generator-form" onSubmit={generate}>
        <label><span>{current.input}</span><textarea required maxLength={tool === "captions" ? 500 : tool === "image" ? 2000 : 5000} value={text} onChange={(e) => setText(e.target.value)} placeholder={current.placeholder} /></label>
        {tool === "image" ? <label><span>SHAPE</span><select value={aspect} onChange={(e) => setAspect(e.target.value)}><option value="1:1">Square 1:1 (feed)</option><option value="4:5">Portrait 4:5 (Instagram feed)</option><option value="9:16">Vertical 9:16 (Reels, TikTok, Stories)</option><option value="16:9">Landscape 16:9 (Facebook, LinkedIn)</option></select></label> : <>
          <div className="ai-option-row">
            <label><span>WHO IS IT FOR?</span><input required={tool === "captions"} maxLength={300} value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="e.g. university students" /></label>
            <label><span>LANGUAGE</span><select value={language} onChange={(e) => setLanguage(e.target.value)}><option>English</option><option>Urdu</option><option>English and Urdu</option></select></label>
          </div>
          <div className="ai-option-row">
            {usesTone && <label><span>TONE</span><select value={tone} onChange={(e) => setTone(e.target.value as Tone)}>{TONES.map((t) => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}</select></label>}
            {usesTone && <label><span>LENGTH</span><select value={length} onChange={(e) => setLength(e.target.value as Length)}><option value="short">Short</option><option value="medium">Medium</option><option value="long">Long-form</option></select></label>}
            {tool === "captions" && <label><span>VARIATIONS</span><select value={variations} onChange={(e) => setVariations(Number(e.target.value))}>{[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>}
            {usesCount && <label><span>HOW MANY</span><select value={count} onChange={(e) => setCount(Number(e.target.value))}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>}
          </div>
          {tool === "captions" && <label><span>FACTS AND BRAND NOTES</span><textarea maxLength={2000} value={facts} onChange={(e) => setFacts(e.target.value)} placeholder="Verified details, required wording, or anything the AI must not assume." /></label>}
          {tool === "captions" && <label className="ai-checkbox"><input type="checkbox" checked={cta} onChange={(e) => setCta(e.target.checked)} /> End with a call to action</label>}
          <fieldset><legend>PLATFORMS</legend><div className="ai-platform-choices">{PLATFORMS.map((p) => <label key={p.id}><input type="checkbox" checked={platforms.includes(p.id)} onChange={() => togglePlatform(p.id)} />{p.label}</label>)}</div></fieldset>
        </>}
        <button className="button button-primary" type="submit" disabled={pending}>{pending ? "Generating…" : tool === "image" ? "Generate image" : "Generate"}</button>
      </form>}
    {error && <p className="ai-generator-error" role="alert">{error}</p>}

    {tool === "image" && image && <div className="ai-image-result">
      {/* eslint-disable-next-line @next/next/no-img-element -- a local blob preview, not an optimisable asset */}
      <img src={image.url} alt="AI-generated preview" />
      <div className="ai-result-actions"><button type="button" className="button button-primary" disabled={saving} onClick={() => void saveImage()}>{saving ? "Saving…" : "Save to library"}</button><Link className="button button-outline" href="/content">Open library</Link></div>
      <small className="ai-note">AI images can contain mistakes. Check them before publishing, and do not depict real people without consent.</small>
    </div>}

    {tool !== "image" && results.length > 0 && <div className="ai-generated-list" aria-live="polite">{results.map((r) => <article className="ai-generated-draft" key={r.key}>
      <div><span>{r.label}{r.title ? ` · ${r.title}` : ""}</span><span className="ai-result-links"><button type="button" onClick={() => copy(r)}>Copy</button><button type="button" onClick={() => sendToComposer(r)}>Use in new post</button></span></div>
      <textarea className="ai-result-text" aria-label={`Edit ${r.label}`} value={r.text} onChange={(e) => edit(r.key, e.target.value)} />
      {r.hashtags.length > 0 && <small>{r.hashtags.map((t) => `#${t.replace(/^#/, "")}`).join(" ")}</small>}
    </article>)}</div>}
    <span className="ai-note">Generated content is a suggestion. Verify facts and platform rules before publishing.</span>
  </section>;
}
