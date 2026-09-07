"""
Step 2 - Web / Social-Media Search
Uses SerpAPI's Google Lens (reverse image search) endpoint to find
social-media posts matching a given face crop image.

Two-step flow (per SerpAPI docs):
  1. POST image to https://serpapi.com/image  --> get image_id
  2. GET  https://serpapi.com/search?engine=google_lens&image_id=...
"""

import os
import sys
import json
import logging
import requests
from pathlib import Path
from PIL import Image
import io

logger = logging.getLogger(__name__)

# Social-media domains we care about (ranked by relevance)
SOCIAL_DOMAINS = [
    "instagram.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "linkedin.com",
    "tiktok.com",
    "reddit.com",
    "pinterest.com",
    "youtube.com",
]

SERPAPI_IMAGE_UPLOAD_URL = "https://serpapi.com/image"
SERPAPI_SEARCH_URL       = "https://serpapi.com/search"
MAX_UPLOAD_BYTES         = 480_000   # SerpAPI limit is 500 KB; use 480 KB to be safe


def _is_social_media(url: str) -> bool:
    return any(domain in url.lower() for domain in SOCIAL_DOMAINS)


def _resize_for_upload(image_path: str) -> bytes:
    """
    Return JPEG bytes of the image, resized if needed to stay under
    SERPAPI's 500 KB upload limit.
    """
    img = Image.open(image_path).convert("RGB")
    quality = 90
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= MAX_UPLOAD_BYTES or quality < 30:
            break
        # Shrink dimensions by 20 % each round
        w, h = img.size
        img = img.resize((int(w * 0.8), int(h * 0.8)), Image.LANCZOS)
        quality = max(30, quality - 10)
    logger.info(f"Image for upload: {len(data)/1024:.1f} KB  ({img.size[0]}x{img.size[1]} px)")
    return data


def _upload_image(image_bytes: bytes, serpapi_key: str) -> str | None:
    """
    Upload image bytes to SerpAPI and return the image_id string,
    or None on failure.
    """
    files = {"image": ("face_crop.jpg", image_bytes, "image/jpeg")}
    data  = {"api_key": serpapi_key}
    try:
        resp = requests.post(SERPAPI_IMAGE_UPLOAD_URL, files=files, data=data, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        image_id = payload.get("image_id")
        if image_id:
            logger.info(f"Image uploaded to SerpAPI. image_id: {image_id}")
        else:
            logger.error(f"SerpAPI upload response missing image_id: {payload}")
        return image_id
    except requests.exceptions.HTTPError as e:
        logger.error(f"SerpAPI image upload HTTP error: {e} -- {resp.text[:300]}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error uploading image: {e}")
        return None


def _lens_search(image_id: str, serpapi_key: str, max_results: int = 10) -> dict:
    """
    Run Google Lens search with a previously uploaded image_id.
    Returns the raw JSON response dict.
    """
    params = {
        "engine":   "google_lens",
        "image_id": image_id,
        "api_key":  serpapi_key,
        "country":  "us",
        "hl":       "en",
    }
    resp = requests.get(SERPAPI_SEARCH_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _parse_results(data: dict, max_results: int = 10) -> list[dict]:
    """Extract hits from a Google Lens API response."""
    hits = []

    for item in data.get("visual_matches", [])[:max_results]:
        hits.append({
            "title":     item.get("title", ""),
            "url":       item.get("link", ""),
            "source":    item.get("source", ""),
            "thumbnail": item.get("thumbnail", ""),
            "is_social": _is_social_media(item.get("link", "")),
        })

    for item in data.get("pages_with_matching_images", [])[:max_results]:
        url = item.get("page_url", "")
        hits.append({
            "title":     item.get("page_title", ""),
            "url":       url,
            "source":    item.get("source", ""),
            "thumbnail": (item.get("thumbnail") or {}).get("link", ""),
            "is_social": _is_social_media(url),
        })

    # Also check knowledge_graph entries
    for kg in data.get("knowledge_graph", []):
        for link in kg.get("links", []):
            url = link.get("link", "")
            hits.append({
                "title":     link.get("text", kg.get("title", "")),
                "url":       url,
                "source":    "",
                "thumbnail": kg.get("image", ""),
                "is_social": _is_social_media(url),
            })

    return hits


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def search_web(face_crop_path: str, serpapi_key: str, max_results: int = 10) -> dict:
    """
    Upload the face crop to SerpAPI Google Lens and return structured results.

    Returns
    -------
    dict with keys:
        success      : bool
        search_url   : str | None
        social_posts : list[dict]
        all_results  : list[dict]
        top_match    : dict | None
        message      : str
        image_id     : str | None
    """
    result = {
        "success":      False,
        "search_url":   None,
        "social_posts": [],
        "all_results":  [],
        "top_match":    None,
        "message":      "",
        "image_id":     None,
    }

    if not os.path.exists(face_crop_path):
        result["message"] = f"Face crop not found: {face_crop_path}"
        logger.error(result["message"])
        return result

    if not serpapi_key:
        result["message"] = "SERPAPI_KEY is not set."
        logger.error(result["message"])
        return result

    # Step A: resize + upload
    logger.info(f"Preparing face crop for upload: {face_crop_path}")
    image_bytes = _resize_for_upload(face_crop_path)

    logger.info("Uploading to SerpAPI Image API ...")
    image_id = _upload_image(image_bytes, serpapi_key)
    if not image_id:
        result["message"] = "Failed to upload image to SerpAPI."
        return result

    result["image_id"] = image_id

    # Step B: Google Lens search
    logger.info("Running Google Lens search ...")
    try:
        data = _lens_search(image_id, serpapi_key, max_results)
    except requests.exceptions.HTTPError as e:
        result["message"] = f"Google Lens search HTTP error: {e}"
        logger.error(result["message"])
        return result
    except requests.exceptions.RequestException as e:
        result["message"] = f"Network error during Google Lens search: {e}"
        logger.error(result["message"])
        return result

    # Extract search URL from metadata
    meta = data.get("search_metadata", {})
    result["search_url"] = (
        meta.get("google_lens_url")
        or meta.get("google_url")
        or f"https://lens.google.com/search?p={image_id}"
    )

    # Parse results
    all_hits   = _parse_results(data, max_results)
    social     = [h for h in all_hits if h["is_social"]]
    result["all_results"]  = all_hits
    result["social_posts"] = social

    if social:
        result["top_match"] = social[0]
        result["success"]   = True
        result["message"]   = (
            f"Found {len(social)} social media result(s). "
            f"Top match: {social[0]['url']}"
        )
        logger.info(result["message"])
    elif all_hits:
        result["top_match"] = all_hits[0]
        result["success"]   = True
        result["message"]   = (
            f"No social posts found, but got {len(all_hits)} web result(s). "
            f"Using top result: {all_hits[0]['url']}"
        )
        logger.warning(result["message"])
    else:
        result["message"] = "No matching results returned by SerpAPI Google Lens."
        logger.warning(result["message"])

    return result


def search_via_url(image_url: str, serpapi_key: str, max_results: int = 10) -> dict:
    """Alternative: search using a publicly accessible image URL."""
    result = {
        "success": False, "search_url": None, "social_posts": [],
        "all_results": [], "top_match": None, "message": "", "image_id": None,
    }

    if not serpapi_key:
        result["message"] = "SERPAPI_KEY is not set."
        return result

    params = {
        "engine": "google_lens", "url": image_url,
        "api_key": serpapi_key, "country": "us", "hl": "en",
    }
    try:
        resp = requests.get(SERPAPI_SEARCH_URL, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        result["message"] = f"Network error: {e}"
        return result

    all_hits = _parse_results(data, max_results)
    social   = [h for h in all_hits if h["is_social"]]
    result.update(
        all_results=all_hits, social_posts=social,
        search_url=data.get("search_metadata", {}).get("google_lens_url", ""),
    )
    if social:
        result.update(top_match=social[0], success=True,
                      message=f"Found {len(social)} social media result(s).")
    elif all_hits:
        result.update(top_match=all_hits[0], success=True,
                      message="No social hits; using first web result.")
    return result


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    key  = os.getenv("SERPAPI_KEY", "")
    crop = sys.argv[1] if len(sys.argv) > 1 else "output/face_crop.png"
    res  = search_web(crop, key)
    print(json.dumps(res, indent=2, default=str))
