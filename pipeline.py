"""
pipeline.py - Main CLI entrypoint for the Face ID & Blockchain Verification pipeline.

Usage
-----
Full pipeline (face scan -> web search -> blockchain upload + verify):
    python pipeline.py --image path/to/face.jpg

Skip blockchain (useful for testing the face + search steps only):
    python pipeline.py --image path/to/face.jpg --no-blockchain

Re-verify a previous run using a saved tx hash:
    python pipeline.py --verify-only output/pipeline_result.json

Search only (provide a pre-cropped face image):
    python pipeline.py --search-only output/face_crop.png
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

import utils
from face_detector import detect_and_encode
from web_searcher import search_web
from blockchain_verifier import upload_to_blockchain, verify_on_blockchain

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = "output"
Path(OUTPUT_DIR).mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _env(key: str, required: bool = True) -> str:
    val = os.getenv(key, "").strip()
    if required and not val:
        utils.error(f"Environment variable {key} is not set.")
        utils.dim(f"  Add it to your .env file (see .env.sample).")
        sys.exit(1)
    return val


def _build_rpc_url() -> str:
    """Build the Infura Sepolia RPC URL from the project ID env var."""
    # Accept either a full URL or just the project ID
    full_url = os.getenv("ETH_RPC_URL", "").strip()
    if full_url:
        return full_url
    project_id = os.getenv("INFURA_PROJECT_ID", "").strip()
    if project_id:
        return f"https://sepolia.infura.io/v3/{project_id}"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Steps
# ─────────────────────────────────────────────────────────────────────────────

def step1_face_detection(image_path: str) -> dict:
    utils.banner("STEP 1 — Face Detection & Encoding")
    result = detect_and_encode(image_path, output_dir=OUTPUT_DIR)

    if result["face_found"]:
        utils.success(result["message"])
        utils.info(f"Face crop saved → {result['face_crop_path']}")
        utils.dim(f"  Embedding hash : {result['embedding_hash']}")
        utils.dim(f"  Faces in image : {result['num_faces']}")
    else:
        utils.error(result["message"])
        sys.exit(1)

    return result


def step2_web_search(image_path: str, face_crop_path: str, serpapi_key: str) -> dict:
    utils.banner("STEP 2 -- Reverse Image Search (Social Media)")
    # Use the full image for better match quality; crop is too small for Google Lens
    search_image = image_path if os.path.exists(image_path) else face_crop_path
    utils.info(f"Searching with: {search_image}")
    result = search_web(search_image, serpapi_key)

    if result["success"]:
        top = result["top_match"]
        utils.success(result["message"])
        utils.info(f"Top match title  : {top.get('title', 'N/A')}")
        utils.info(f"Top match URL    : {top.get('url', 'N/A')}")
        utils.info(f"Source           : {top.get('source', 'N/A')}")
        if result.get("search_url"):
            utils.dim(f"  Google Lens URL: {result['search_url']}")
        if result["social_posts"]:
            utils.info(f"Social hits      : {len(result['social_posts'])}")
    else:
        utils.error(result["message"])
        sys.exit(1)

    return result


def step3_blockchain_upload(post: dict, rpc_url: str, private_key: str, wallet_address: str) -> dict:
    utils.banner("STEP 3 — Blockchain Upload (Ethereum Sepolia Testnet)")
    result = upload_to_blockchain(post, rpc_url, private_key, wallet_address)

    if result["success"]:
        utils.success(result["message"])
        utils.info(f"Data hash  : {result['data_hash']}")
        utils.info(f"Tx hash    : {result['tx_hash']}")
        utils.info(f"Block #    : {result['block_number']}")
        utils.info(f"Gas used   : {result['gas_used']}")
        utils.success(f"Etherscan  : {result['etherscan_url']}")
    else:
        utils.error(result["message"])
        sys.exit(1)

    return result


def step4_verify(post: dict, tx_hash: str, rpc_url: str) -> dict:
    utils.banner("STEP 4 — On-Chain Verification")
    result = verify_on_blockchain(post, tx_hash, rpc_url)

    if result["verified"]:
        utils.success(result["message"])
        utils.dim(f"  Local hash   : {result['local_hash']}")
        utils.dim(f"  On-chain hash: {result['on_chain_hash']}")
        utils.dim(f"  Block #      : {result['block_number']}")
        utils.info(f"  Etherscan    : {result['etherscan_url']}")
    else:
        utils.error(result["message"])

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Verify-only mode (re-run from saved result)
# ─────────────────────────────────────────────────────────────────────────────

def run_verify_only(result_json_path: str) -> None:
    utils.banner("RE-VERIFICATION MODE")
    if not os.path.exists(result_json_path):
        utils.error(f"Result file not found: {result_json_path}")
        sys.exit(1)

    saved = utils.load_json(result_json_path)
    post    = saved.get("top_match_post", {})
    tx_hash = saved.get("tx_hash", "")
    rpc_url = _build_rpc_url()

    if not tx_hash:
        utils.error("No tx_hash found in saved result file.")
        sys.exit(1)

    utils.info(f"Loaded saved result: {result_json_path}")
    utils.info(f"Tx hash : {tx_hash}")

    step4_verify(post, tx_hash, rpc_url)


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(image_path: str, no_blockchain: bool = False) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Read env variables
    serpapi_key    = _env("SERPAPI_KEY")
    rpc_url        = _build_rpc_url()
    private_key    = "" if no_blockchain else _env("ETH_PRIVATE_KEY")
    wallet_address = "" if no_blockchain else _env("ETH_WALLET_ADDRESS")

    if not no_blockchain and not rpc_url:
        utils.error("ETH_RPC_URL or INFURA_PROJECT_ID is not set.")
        sys.exit(1)

    utils.banner(f"🔍  Face ID & Blockchain Verification Pipeline  ({ts})")
    utils.info(f"Input image: {image_path}")

    pipeline_result = {
        "timestamp": utils.utc_now(),
        "input_image": image_path,
    }

    # Step 1
    face_result = step1_face_detection(image_path)
    pipeline_result["face_detection"] = {
        k: v for k, v in face_result.items() if k != "embedding"  # skip large embedding array
    }
    pipeline_result["embedding_hash"] = face_result["embedding_hash"]

    # Step 2
    search_result = step2_web_search(image_path, face_result["face_crop_path"], serpapi_key)
    pipeline_result["web_search"] = {
        "success":      search_result["success"],
        "message":      search_result["message"],
        "search_url":   search_result["search_url"],
        "social_posts": search_result["social_posts"],
        "all_results":  search_result["all_results"][:5],  # save top 5 only
    }

    top_match = search_result["top_match"]
    # Enrich post with search_url for better fingerprinting
    top_match_post = {
        **top_match,
        "search_url": search_result.get("search_url", ""),
    }
    pipeline_result["top_match_post"] = top_match_post

    if no_blockchain:
        utils.banner("Blockchain steps skipped (--no-blockchain flag)")
        out_path = os.path.join(OUTPUT_DIR, f"pipeline_result_{ts}.json")
        utils.save_json(pipeline_result, out_path)
        utils.success(f"Pipeline complete (no blockchain). Result saved → {out_path}")
        return

    # Step 3
    bc_result = step3_blockchain_upload(top_match_post, rpc_url, private_key, wallet_address)
    pipeline_result.update({
        "tx_hash":      bc_result["tx_hash"],
        "etherscan_url":bc_result["etherscan_url"],
        "block_number": bc_result["block_number"],
        "data_hash":    bc_result["data_hash"],
    })
    pipeline_result["blockchain_upload"] = bc_result

    # Step 4
    verify_result = step4_verify(top_match_post, bc_result["tx_hash"], rpc_url)
    pipeline_result["verification"] = verify_result

    # Save full result
    out_path = os.path.join(OUTPUT_DIR, f"pipeline_result_{ts}.json")
    utils.save_json(pipeline_result, out_path)

    utils.banner("PIPELINE COMPLETE")
    if verify_result["verified"]:
        utils.success("End-to-end verification passed! ✅")
    else:
        utils.warn("Verification failed — see details above.")

    utils.info(f"Full result saved → {out_path}")
    utils.info(f"Etherscan link   → {bc_result['etherscan_url']}")


# ─────────────────────────────────────────────────────────────────────────────
# Search-only mode
# ─────────────────────────────────────────────────────────────────────────────

def run_search_only(crop_path: str) -> None:
    serpapi_key = _env("SERPAPI_KEY")
    result = step2_web_search(crop_path, serpapi_key)
    print(json.dumps(result, indent=2, default=str))


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Face ID & Blockchain Verification Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image",       metavar="PATH", help="Input image with a face (full pipeline)")
    group.add_argument("--verify-only", metavar="JSON", help="Re-verify using a saved pipeline_result.json")
    group.add_argument("--search-only", metavar="CROP", help="Reverse-image-search a pre-cropped face image")

    parser.add_argument(
        "--no-blockchain",
        action="store_true",
        default=False,
        help="Skip blockchain steps (useful for testing face detection + search only)",
    )

    args = parser.parse_args()

    if args.verify_only:
        run_verify_only(args.verify_only)
    elif args.search_only:
        run_search_only(args.search_only)
    else:
        run_pipeline(args.image, no_blockchain=args.no_blockchain)


if __name__ == "__main__":
    main()
