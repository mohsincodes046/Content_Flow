"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";

type Platform = "instagram" | "facebook" | "linkedin" | "youtube" | "tiktok";
type UploadedAsset = {
  id: string;
  filename: string;
  media_type: string;
  size: number;
};
type Submission = {
  id: string;
  campaign: string;
  audience: string;
  instructions: string;
  language: string;
  platforms: Platform[];
  assets: UploadedAsset[];
  status: "submitted";
  created_at: string;
};

const apiUrl = (process.env.NEXT_PUBLIC_CONTENT_FLOW_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const platforms: Array<{ id: Platform; name: string; icon: string; color: string }> = [
  { id: "instagram", name: "Instagram", icon: "◎", color: "#d95776" },
  { id: "facebook", name: "Facebook", icon: "f", color: "#4d76e9" },
  { id: "linkedin", name: "LinkedIn", icon: "in", color: "#3285bd" },
  { id: "youtube", name: "YouTube", icon: "▶", color: "#e8584d" },
  { id: "tiktok", name: "TikTok", icon: "♪", color: "#29272d" },
];

function isAsset(value: unknown): value is UploadedAsset {
  if (typeof value !== "object" || value === null) return false;
  const asset = value as Partial<UploadedAsset>;
  return typeof asset.id === "string"
    && typeof asset.filename === "string"
    && typeof asset.media_type === "string"
    && typeof asset.size === "number";
}

function isSubmission(value: unknown): value is Submission {
  if (typeof value !== "object" || value === null) return false;
  const submission = value as Partial<Submission>;
  return typeof submission.id === "string"
    && typeof submission.campaign === "string"
    && typeof submission.audience === "string"
    && typeof submission.instructions === "string"
    && typeof submission.language === "string"
    && Array.isArray(submission.platforms)
    && submission.platforms.every((platform) => platforms.some((item) => item.id === platform))
    && Array.isArray(submission.assets)
    && submission.assets.every(isAsset)
    && submission.status === "submitted"
    && typeof submission.created_at === "string";
}

async function responseError(response: Response) {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = body.detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail.map((item) => typeof item === "object" && item !== null && "msg" in item
          ? String(item.msg)
          : "Invalid request").join(" ");
      }
    }
  } catch (error) {
    console.error("Unable to read API error response.", error);
  }
  return `The server returned an error (${response.status}). Please try again.`;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function SubmissionWorkflow({
  view,
  setNotice,
}: {
  view: "submit" | "review";
  setNotice: (notice: string) => void;
}) {
  const router = useRouter();
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [uploadedAssets, setUploadedAssets] = useState<UploadedAsset[]>([]);
  const [selectedPlatforms, setSelectedPlatforms] = useState<Platform[]>(["instagram", "facebook", "linkedin"]);
  const [apiError, setApiError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function loadSubmissions() {
      try {
        const response = await fetch(`${apiUrl}/api/submissions`, { credentials: "include", signal: controller.signal });
        if (!response.ok) throw new Error(await responseError(response));
        const result: unknown = await response.json();
        if (!Array.isArray(result) || !result.every(isSubmission)) {
          throw new Error("The server returned submissions in an unexpected format.");
        }
        setSubmissions(result);
        setApiError("");
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("Unable to load submissions from the Content-Flow API.", error);
        setApiError(error instanceof Error
          ? `Couldn't reach the backend: ${error.message}. Make sure the API is running at ${apiUrl}.`
          : `Couldn't reach the backend at ${apiUrl}. Make sure the API is running.`);
      } finally {
        if (!controller.signal.aborted) setReady(true);
      }
    }

    void loadSubmissions();
    return () => controller.abort();
  }, []);

  async function updateFiles(event: ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(event.target.files ?? []);
    event.target.value = "";
    const accepted = chosen.filter(
      (file) => (file.type.startsWith("image/") || file.type.startsWith("video/"))
        && file.size <= 50 * 1024 * 1024,
    );
    if (accepted.length > 20) {
      setApiError("A submission can contain up to 20 media files. Select 20 or fewer.");
      setFiles([]);
      setUploadedAssets([]);
      return;
    }
    const skippedFiles = accepted.length !== chosen.length;
    setApiError(skippedFiles ? "Only image or video files under 50 MB each can be uploaded. Unsupported files will be skipped." : "");

    setFiles(accepted);
    setUploadedAssets([]);
    if (accepted.length === 0) return;

    setIsUploading(true);
    const assets: UploadedAsset[] = [];
    try {
      for (const file of accepted) {
        const body = new FormData();
        body.append("file", file);
        const response = await fetch(`${apiUrl}/api/assets`, { method: "POST", credentials: "include", body });
        if (!response.ok) throw new Error(await responseError(response));
        const asset: unknown = await response.json();
        if (!isAsset(asset)) throw new Error("The server returned an unexpected upload response.");
        assets.push(asset);
        setUploadedAssets([...assets]);
      }
      setApiError(skippedFiles ? "Some files were skipped. The accepted files have been uploaded successfully." : "");
    } catch (error) {
      console.error("Unable to upload selected content to the Content-Flow API.", error);
      setApiError(error instanceof Error
        ? `File upload failed: ${error.message}. ${assets.length ? "Successfully uploaded files can still be submitted; reselect the remaining files to retry." : "Select the files again to retry."}`
        : "File upload failed. Successfully uploaded files can still be submitted; reselect the remaining files to retry.");
      setFiles(accepted.slice(0, assets.length));
      setUploadedAssets(assets);
    } finally {
      setIsUploading(false);
    }
  }

  function togglePlatform(platform: Platform) {
    setSelectedPlatforms((current) => current.includes(platform)
      ? current.filter((item) => item !== platform)
      : [...current, platform]);
  }

  async function submitContent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedPlatforms.length === 0) {
      setApiError("Choose at least one platform for this content.");
      return;
    }
    if (isUploading || uploadedAssets.length !== files.length) {
      setApiError("Wait for every selected file to finish uploading before submitting.");
      return;
    }

    const formData = new FormData(event.currentTarget);
    const payload = {
      campaign: String(formData.get("campaign") ?? "").trim(),
      audience: String(formData.get("audience") ?? "").trim(),
      instructions: String(formData.get("instructions") ?? "").trim(),
      language: String(formData.get("language") ?? "English"),
      platforms: selectedPlatforms,
      asset_ids: uploadedAssets.map((asset) => asset.id),
    };

    setIsSubmitting(true);
    try {
      const response = await fetch(`${apiUrl}/api/submissions`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result: unknown = await response.json();
      if (!isSubmission(result)) throw new Error("The server returned an unexpected submission response.");
      const created = result;
      setSubmissions((current) => [created, ...current]);
      setFiles([]);
      setUploadedAssets([]);
      setApiError("");
      setNotice("Content submission saved on the backend. AI drafting and publishing are not connected yet.");
      router.push("/review-queue");
    } catch (error: unknown) {
      console.error("Unable to create a submission through the Content-Flow API.", error);
      setApiError(error instanceof Error ? error.message : "The submission could not be saved. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (view === "review") {
    return (
      <>
        <div className="page-heading workflow-page-heading">
          <div>
            <div className="eyebrow page-eyebrow"><span className="live-dot" /> HUMAN REVIEW FIRST</div>
            <h1>Review queue</h1>
            <p>AI drafts will appear here for your team to check before anything is scheduled.</p>
          </div>
          <div className="heading-actions">
            <Link className="button button-primary" href="/create-post">＋ Submit content</Link>
          </div>
        </div>
        <div className="workflow-notice"><span>i</span><p><b>Backend connected.</b> Submissions and uploaded files are saved on the local Content-Flow server. AI drafting, approval actions, and social publishing still need to be connected.</p></div>
        {apiError && <p className="workflow-error" role="alert">{apiError}</p>}
        {!ready ? <div className="panel workflow-empty"><b>Loading submissions…</b></div> : submissions.length === 0 ? (
          <div className="panel workflow-empty">
            <span className="workflow-empty-icon">✳</span>
            <h2>Your review queue is clear.</h2>
            <p>Once you submit content, its automation status will show up here.</p>
            <Link className="button button-primary" href="/create-post">Submit your first piece of content</Link>
          </div>
        ) : (
          <div className="workflow-queue">
            {submissions.map((submission) => (
              <article className="panel workflow-submission" key={submission.id}>
                <div className="workflow-submission-heading">
                  <div>
                    <span className="workflow-status"><i /> Submitted · awaiting AI setup</span>
                    <h2>{submission.campaign || "Untitled content submission"}</h2>
                    <p>Submitted {formatDate(submission.created_at)}</p>
                  </div>
                  <span className="workflow-step">1 <span>›</span> 2 <span>›</span> 3</span>
                </div>
                <div className="workflow-submission-details">
                  <div><span>ASSETS</span><b>{submission.assets.length ? submission.assets.map((asset) => asset.filename).join(", ") : "Text-only post"}</b></div>
                  <div><span>AUDIENCE</span><b>{submission.audience}</b></div>
                  <div><span>LANGUAGE</span><b>{submission.language}</b></div>
                </div>
                <div className="workflow-destinations">
                  <span>PLATFORM VERSIONS REQUESTED</span>
                  <div>{submission.platforms.map((id) => {
                    const platform = platforms.find((item) => item.id === id);
                    return platform ? <span className="workflow-platform" key={id}><i style={{ "--account-color": platform.color } as React.CSSProperties}>{platform.icon}</i>{platform.name}</span> : null;
                  })}</div>
                </div>
                <details className="workflow-instructions">
                  <summary>Content instructions</summary>
                  <p>{submission.instructions}</p>
                </details>
              </article>
            ))}
          </div>
        )}
      </>
    );
  }

  return (
    <>
      <div className="page-heading workflow-page-heading">
        <div>
          <div className="eyebrow page-eyebrow"><span className="live-dot" /> CONTENT IN, READY-TO-REVIEW DRAFTS OUT</div>
          <h1>Submit content</h1>
          <p>Share the asset and the context. Your automation can prepare a version for each platform.</p>
        </div>
        <div className="heading-actions">
          <Link className="button button-white" href="/review-queue">View review queue <span className="workflow-count">{submissions.length}</span></Link>
        </div>
      </div>

      <div className="workflow-notice"><span>i</span><p><b>Backend connected.</b> Uploaded files and submissions are saved on the local server. AI generation and social publishing are not connected yet.</p></div>
      {apiError && <p className="workflow-error" role="alert" aria-live="polite">{apiError}</p>}

      <form className="workflow-form" onSubmit={submitContent}>
        <div className="workflow-form-main">
          <section className="panel workflow-panel">
            <div className="workflow-section-heading"><span className="workflow-step-number">01</span><div><h2>Share your content</h2><p>Add a video, image, or submit text on its own.</p></div></div>
            <label className="workflow-upload">
              <span className="workflow-upload-icon">↥</span>
              <b>{isUploading ? "Uploading files to Content-Flow…" : files.length ? `${uploadedAssets.length} of ${files.length} file${files.length === 1 ? "" : "s"} uploaded` : "Drop files here or browse"}</b>
              <small>Images and videos · up to 50 MB each</small>
              {files.length > 0 && <span className="workflow-file-list">{files.map((file) => file.name).join(" · ")}</span>}
              <input aria-label="Choose images or videos" type="file" accept="image/*,video/*" multiple disabled={isUploading || isSubmitting} onChange={updateFiles} />
            </label>
            <p className="workflow-local-note">Files are uploaded to the local backend when selected. Up to 20 files can be attached to a submission.</p>
            <label className="workflow-field"><span>CAMPAIGN OR POST NAME <em>OPTIONAL</em></span><input name="campaign" placeholder="e.g. AI course launch" maxLength={100} /></label>
            <label className="workflow-field"><span>WHAT SHOULD THE AI KNOW? <em>YOUR INSTRUCTIONS</em></span><textarea name="instructions" required rows={5} maxLength={2000} placeholder="Describe what the content is about, the key message, any call to action, and anything the AI must not assume. For example: promote our AI course to students and professionals; don't invent fees or dates." /></label>
          </section>

          <section className="panel workflow-panel">
            <div className="workflow-section-heading"><span className="workflow-step-number">02</span><div><h2>Set the context</h2><p>Help the AI write for the right people, in the right language.</p></div></div>
            <div className="workflow-context-grid">
              <label className="workflow-field"><span>TARGET AUDIENCE</span><input name="audience" required placeholder="e.g. University students and working professionals" maxLength={160} /></label>
              <label className="workflow-field"><span>PREFERRED LANGUAGE</span><select name="language" defaultValue="English"><option>English</option><option>Urdu</option><option>English and Urdu</option></select></label>
            </div>
            <div className="workflow-field"><span>IMPORTANT FACTS OR BRAND NOTES <em>ADD TO YOUR INSTRUCTIONS ABOVE</em></span><small className="workflow-helper">Include verified course names, dates, links, or approved wording. The AI should not make up missing details.</small></div>
          </section>
        </div>

        <aside className="workflow-form-side">
          <section className="panel workflow-panel workflow-platform-panel">
            <div className="workflow-section-heading"><span className="workflow-step-number">03</span><div><h2>Choose platforms</h2><p>Each network gets its own tailored draft.</p></div></div>
            <div className="workflow-platform-list">{platforms.map((platform) => (
              <label className="workflow-platform-choice" key={platform.id}>
                <input type="checkbox" checked={selectedPlatforms.includes(platform.id)} onChange={() => togglePlatform(platform.id)} />
                <i style={{ "--account-color": platform.color } as React.CSSProperties}>{platform.icon}</i>
                <span>{platform.name}</span>
              </label>
            ))}</div>
            <p className="workflow-local-note">Platforms are saved as your publishing targets. Connect accounts and automation before using real campaigns.</p>
            <button className="button button-primary workflow-submit" type="submit" disabled={!ready || isUploading || isSubmitting || uploadedAssets.length !== files.length}>{isSubmitting ? "Saving submission…" : isUploading ? "Uploading files…" : "Save submission"} <span>↗</span></button>
            <p className="workflow-approval-note">Nothing is published automatically. A person reviews and approves drafts first.</p>
          </section>
        </aside>
      </form>
    </>
  );
}
