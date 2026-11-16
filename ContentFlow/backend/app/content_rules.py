"""Platform rules checked before a post is scheduled or published.

Sources: Meta's Instagram content publishing reference (JPEG images ≤ 8 MB with
an aspect ratio between 4:5 and 1.91:1, MP4/MOV video, carousels of up to 20
items, captions ≤ 2,200 characters, ≤ 30 hashtags, ≤ 20 @mentions) and Facebook
Page posting (text, photos or a single video; captions ≤ 63,206 characters).
PNG, WebP and large JPEG images are converted to an Instagram-ready JPEG
automatically, so they are not errors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

HASHTAG = re.compile(r"(?<!\w)#\w+")
MENTION = re.compile(r"(?<![\w@])@[\w.]+")

LIMITS = {
    "facebook": {"caption": 63206, "items": 10},
    "instagram": {"caption": 2200, "items": 20, "hashtags": 30, "mentions": 20},
}


@dataclass
class Media:
    media_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    size: int = 0

    @property
    def is_video(self) -> bool:
        return self.media_type.startswith("video/")


@dataclass
class Issue:
    platform: str
    message: str
    account: Optional[str] = None


def check(platform: str, caption: str, media: list[Media], account: Optional[str] = None) -> list[Issue]:
    issues: list[Issue] = []

    def add(message: str) -> None:
        issues.append(Issue(platform, message, account))

    if platform == "facebook":
        if not caption.strip() and not media:
            add("Add a caption or media.")
        if len(caption) > LIMITS["facebook"]["caption"]:
            add(f"Facebook captions can be at most {LIMITS['facebook']['caption']:,} characters.")
        videos = [m for m in media if m.is_video]
        if videos and len(media) > 1:
            add("Facebook posts can have several photos or one video, not both.")
        if len(media) > LIMITS["facebook"]["items"]:
            add(f"Facebook posts can have at most {LIMITS['facebook']['items']} photos here.")
        if any(m.media_type == "image/webp" for m in media):
            add("Facebook does not accept WebP photos; use JPEG or PNG.")
    elif platform == "instagram":
        rules = LIMITS["instagram"]
        if not media:
            add("Instagram posts need at least one photo or video.")
        if len(media) > rules["items"]:
            add(f"Instagram carousels can have at most {rules['items']} items.")
        if len(caption) > rules["caption"]:
            add(f"Instagram captions can be at most {rules['caption']:,} characters.")
        if len(HASHTAG.findall(caption)) > rules["hashtags"]:
            add(f"Instagram allows at most {rules['hashtags']} hashtags.")
        if len(MENTION.findall(caption)) > rules["mentions"]:
            add(f"Instagram allows at most {rules['mentions']} @mentions.")
        for index, item in enumerate(media, start=1):
            label = f"Item {index}" if len(media) > 1 else "The image"
            if item.media_type == "image/gif":
                add(f"{label}: Instagram does not accept GIFs.")
            if not item.is_video and item.width and item.height:
                ratio = item.width / item.height
                if ratio < 0.8 - 0.01 or ratio > 1.91 + 0.01:
                    add(f"{label}: Instagram needs an aspect ratio between 4:5 (portrait) and 1.91:1 "
                        f"(landscape); this one is {item.width}×{item.height}.")
    elif platform == "tiktok":
        videos = [m for m in media if m.is_video]
        if len(media) != 1 or len(videos) != 1:
            add("TikTok posts need exactly one video.")
        if len(caption) > 2200:
            add("TikTok captions can be at most 2,200 characters.")
    elif platform == "linkedin":
        if not caption.strip() and not media:
            add("Add text or an image.")
        if len(caption) > 3000:
            add("LinkedIn posts can be at most 3,000 characters.")
        if any(m.is_video for m in media):
            add("LinkedIn video posts are not supported yet; use text or one image.")
        elif len(media) > 1:
            add("LinkedIn posts here can have one image.")
    else:
        add(f"Publishing to {platform} is not available yet.")
    return issues
