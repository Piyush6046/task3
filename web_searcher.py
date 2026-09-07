"""
Step 2 – Web / Social-Media Search
Uses SerpAPI's Google Lens (reverse image search) endpoint to find
social-media posts matching a given face crop image.
"""

import os
import sys
import json
import logging
import requests
from pathlib import Path

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


def _is_social_media(url: str) -> bool:
    return any(domain in url.lower() for domain in SOCIAL_DOMAINS)


def search_web(face_crop_path: str, serpapi_key: str, max_results: int = 10) -> dict:
    """
    Upload the face crop to SerpAPI Google Lens and return structured results.

    Parameters
    ----------
    face_crop_path : str   – path to the saved face-crop PNG
    serpapi_key    : str   – your SerpAPI API key
    max_results    : int   – max number of results to return

    Returns
    -------
    dict with keys:
        success          : bool
        search_url       : str | None   (Google Lens search URL)
        social_posts     : list[dict]   (ranked social-media hits)
        all_results      : list[dict]   (every result returned)
        top_match        : dict | None  (best social-media result)
        message          : str
    """
    result = {
        "success": False,
        "search_url": None,
        "social_posts": [],
        "all_results": [],
        "top_match": None,
        "message": "",
    }

    if not os.path.exists(face_crop_path):
        result["message"] = f"Face crop not found: {face_crop_path}"
        logger.error(result["message"])
        return result

    if not serpapi_key:
        result["message"] = "SERPAPI_KEY is not set."
        logger.error(result["message"])
        return result

    logger.info(f"Uploading face crop to SerpAPI Google Lens: {face_crop_path}")

    # ------------------------------------------------------------------ #
    # SerpAPI Google Lens – upload image as multipart/form-data           #
    # ------------------------------------------------------------------ #
    try:
        with open(face_crop_path, "rb") as f:
            files = {"image": (Path(face_crop_path).name, f, "image/png")}
            params = {
                "engine": "google_lens",
                "api_key": serpapi_key,
                "country": "us",
                "hl": "en",
            }
            resp = requests.post(
                "https://serpapi.com/search",
                params=params,
                files=files,
                timeout=60,
            )

        resp.raise_for_status()
        data = resp.json()

    except requests.exceptions.HTTPError as e:
        result["message"] = f"SerpAPI HTTP error: {e} — {resp.text[:200]}"
        logger.error(result["message"])
        return result
    except requests.exceptions.RequestException as e:
        result["message"] = f"Network error calling SerpAPI: {e}"
        logger.error(result["message"])
        return result

    # ------------------------------------------------------------------ #
    # Parse response                                                       #
    # ------------------------------------------------------------------ #
    search_metadata = data.get("search_metadata", {})
    result["search_url"] = search_metadata.get("google_lens_url") or search_metadata.get("google_url")

    # Google Lens returns visual_matches and/or knowledge_graph
    visual_matches = data.get("visual_matches", [])
    knowledge_graph = data.get("knowledge_graph", [])

    all_hits = []
    for item in visual_matches[:max_results]:
        hit = {
            "title":    item.get("title", ""),
            "url":      item.get("link", ""),
            "source":   item.get("source", ""),
            "thumbnail":item.get("thumbnail", ""),
            "is_social":_is_social_media(item.get("link", "")),
        }
        all_hits.append(hit)

    # Also check inline_images and pages_with_matching_images (classic reverse search)
    pages = data.get("pages_with_matching_images", [])
    for item in pages[:max_results]:
        hit = {
            "title":    item.get("page_title", ""),
            "url":      item.get("page_url", ""),
            "source":   item.get("source", ""),
            "thumbnail":item.get("thumbnail", {}).get("link", "") if isinstance(item.get("thumbnail"), dict) else "",
            "is_social":_is_social_media(item.get("page_url", "")),
        }
        all_hits.append(hit)

    result["all_results"] = all_hits

    # Filter to social media posts
    social = [h for h in all_hits if h["is_social"]]
    result["social_posts"] = social

    if social:
        result["top_match"] = social[0]
        result["success"] = True
        result["message"] = (
            f"Found {len(social)} social media result(s). "
            f"Top match: {social[0]['url']}"
        )
        logger.info(result["message"])
    elif all_hits:
        # No social media hit, but we have other web results — use the first one
        result["top_match"] = all_hits[0]
        result["success"] = True
        result["message"] = (
            f"No social media posts found, but got {len(all_hits)} web result(s). "
            f"Using: {all_hits[0]['url']}"
        )
        logger.warning(result["message"])
    else:
        result["message"] = "No matching results returned by SerpAPI."
        logger.warning(result["message"])

    return result


def search_via_url(image_url: str, serpapi_key: str, max_results: int = 10) -> dict:
    """
    Alternative: search using a publicly accessible image URL instead of uploading.
    """
    result = {
        "success": False,
        "search_url": None,
        "social_posts": [],
        "all_results": [],
        "top_match": None,
        "message": "",
    }

    if not serpapi_key:
        result["message"] = "SERPAPI_KEY is not set."
        return result

    params = {
        "engine": "google_lens",
        "url": image_url,
        "api_key": serpapi_key,
        "country": "us",
        "hl": "en",
    }

    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        result["message"] = f"Network error: {e}"
        return result

    visual_matches = data.get("visual_matches", [])
    all_hits = []
    for item in visual_matches[:max_results]:
        hit = {
            "title":    item.get("title", ""),
            "url":      item.get("link", ""),
            "source":   item.get("source", ""),
            "thumbnail":item.get("thumbnail", ""),
            "is_social":_is_social_media(item.get("link", "")),
        }
        all_hits.append(hit)

    social = [h for h in all_hits if h["is_social"]]
    result["all_results"] = all_hits
    result["social_posts"] = social
    result["search_url"] = data.get("search_metadata", {}).get("google_lens_url", "")

    if social:
        result["top_match"] = social[0]
        result["success"] = True
        result["message"] = f"Found {len(social)} social media result(s)."
    elif all_hits:
        result["top_match"] = all_hits[0]
        result["success"] = True
        result["message"] = f"No social hits, using first web result."

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    key = os.getenv("SERPAPI_KEY", "")
    crop = sys.argv[1] if len(sys.argv) > 1 else "output/face_crop.png"
    res = search_web(crop, key)
    print(json.dumps(res, indent=2, default=str))
