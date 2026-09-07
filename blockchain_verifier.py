"""
Steps 3 & 4 – Blockchain Upload & Verification
Hashes the discovered post metadata, stores it on the Ethereum Sepolia
testnet (via an ETH self-transfer with the hash in the `data` field),
and later re-verifies the data matches what is on chain.
"""

import os
import sys
import json
import hashlib
import time
import logging
from typing import Optional

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware  # for PoA chains

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compute_hash(post: dict) -> str:
    """
    Create a deterministic SHA-256 fingerprint of the post metadata.
    Fields included: url, title, source, search_url (if available).
    """
    canonical = json.dumps(
        {
            "url":        post.get("url", ""),
            "title":      post.get("title", ""),
            "source":     post.get("source", ""),
            "search_url": post.get("search_url", ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _connect(rpc_url: str) -> Optional[Web3]:
    """Return a connected Web3 instance or None."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    # Inject PoA middleware (needed for Sepolia / Goerli)
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if w3.is_connected():
        logger.info(f"Connected to {rpc_url}  (chain_id={w3.eth.chain_id})")
        return w3
    logger.error(f"Could not connect to RPC: {rpc_url}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Upload
# ─────────────────────────────────────────────────────────────────────────────

def upload_to_blockchain(
    post: dict,
    rpc_url: str,
    private_key: str,
    wallet_address: str,
) -> dict:
    """
    Compute SHA-256 of post metadata and store it on-chain.

    The hash is embedded as the `data` field (hex) of an ETH self-transfer
    to `wallet_address`.  This is verifiable by anyone who reads the tx.

    Returns
    -------
    dict with keys:
        success        : bool
        data_hash      : str   (the SHA-256 hex string committed on chain)
        tx_hash        : str | None
        etherscan_url  : str | None
        block_number   : int | None
        gas_used       : int | None
        message        : str
    """
    result = {
        "success": False,
        "data_hash": None,
        "tx_hash": None,
        "etherscan_url": None,
        "block_number": None,
        "gas_used": None,
        "message": "",
    }

    # Validate inputs
    if not rpc_url:
        result["message"] = "RPC_URL / INFURA_PROJECT_ID is not set."
        logger.error(result["message"])
        return result
    if not private_key:
        result["message"] = "ETH_PRIVATE_KEY is not set."
        logger.error(result["message"])
        return result
    if not wallet_address:
        result["message"] = "ETH_WALLET_ADDRESS is not set."
        logger.error(result["message"])
        return result

    w3 = _connect(rpc_url)
    if w3 is None:
        result["message"] = "Failed to connect to Ethereum node."
        return result

    # Compute the hash
    data_hash = _compute_hash(post)
    result["data_hash"] = data_hash
    logger.info(f"Data hash: {data_hash}")

    # Encode hash as hex bytes for the tx data field
    data_bytes = bytes.fromhex(data_hash)   # 32 raw bytes
    data_hex   = "0x" + data_hash           # hex string for Web3

    checksum_address = Web3.to_checksum_address(wallet_address)

    try:
        nonce = w3.eth.get_transaction_count(checksum_address, "pending")
        gas_price = w3.eth.gas_price

        tx = {
            "nonce":    nonce,
            "to":       checksum_address,   # self-transfer
            "value":    0,                  # 0 ETH
            "gas":      50_000,
            "gasPrice": gas_price,
            "chainId":  w3.eth.chain_id,
            "data":     data_hex,
        }

        signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash_hex = tx_hash.hex()
        logger.info(f"Transaction sent: {tx_hash_hex}")

        # Wait for receipt (up to 120 s)
        logger.info("Waiting for confirmation …")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt["status"] == 1:
            etherscan_url = f"https://sepolia.etherscan.io/tx/{tx_hash_hex}"
            result.update(
                success=True,
                tx_hash=tx_hash_hex,
                etherscan_url=etherscan_url,
                block_number=receipt["blockNumber"],
                gas_used=receipt["gasUsed"],
                message=f"On-chain record created! Block #{receipt['blockNumber']}",
            )
            logger.info(result["message"])
        else:
            result["message"] = "Transaction reverted on chain."
            logger.error(result["message"])

    except Exception as e:
        result["message"] = f"Blockchain error: {e}"
        logger.exception(result["message"])

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Verify
# ─────────────────────────────────────────────────────────────────────────────

def verify_on_blockchain(
    post: dict,
    tx_hash: str,
    rpc_url: str,
) -> dict:
    """
    Re-hash the post metadata and compare against what is stored in the
    transaction's `input` (data) field on chain.

    Returns
    -------
    dict with keys:
        verified       : bool
        local_hash     : str   (freshly computed SHA-256)
        on_chain_hash  : str | None
        tx_hash        : str
        block_number   : int | None
        etherscan_url  : str
        message        : str
    """
    result = {
        "verified": False,
        "local_hash": None,
        "on_chain_hash": None,
        "tx_hash": tx_hash,
        "block_number": None,
        "etherscan_url": f"https://sepolia.etherscan.io/tx/{tx_hash}",
        "message": "",
    }

    if not rpc_url:
        result["message"] = "RPC_URL is not set."
        return result

    w3 = _connect(rpc_url)
    if w3 is None:
        result["message"] = "Failed to connect to Ethereum node."
        return result

    # Local hash
    local_hash = _compute_hash(post)
    result["local_hash"] = local_hash

    try:
        tx_data = w3.eth.get_transaction(tx_hash)
    except Exception as e:
        result["message"] = f"Could not fetch transaction: {e}"
        logger.error(result["message"])
        return result

    # Extract hash from tx input field
    raw_input = tx_data.get("input", b"")
    if isinstance(raw_input, bytes):
        on_chain_hash = raw_input.hex()
    else:
        on_chain_hash = str(raw_input)

    # Strip leading '0x'
    on_chain_hash = on_chain_hash.lstrip("0x").lower()
    result["on_chain_hash"] = on_chain_hash

    block_number = tx_data.get("blockNumber")
    result["block_number"] = block_number

    if local_hash.lower() == on_chain_hash:
        result["verified"] = True
        result["message"] = (
            f"[OK] VERIFIED -- Hash matches on-chain record in block #{block_number}."
        )
        logger.info(result["message"])
    else:
        result["message"] = (
            f"[FAILED] VERIFICATION FAILED -- Hash mismatch.\n"
            f"   Local hash   : {local_hash}\n"
            f"   On-chain hash: {on_chain_hash}"
        )
        logger.warning(result["message"])

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    rpc     = os.getenv("ETH_RPC_URL", "")
    key     = os.getenv("ETH_PRIVATE_KEY", "")
    address = os.getenv("ETH_WALLET_ADDRESS", "")

    if len(sys.argv) < 2:
        print("Usage: python blockchain_verifier.py upload|verify [args]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "upload":
        # Quick test with a dummy post
        post = {"url": "https://example.com/post", "title": "Test", "source": "example.com"}
        res = upload_to_blockchain(post, rpc, key, address)
        print(json.dumps(res, indent=2))
    elif cmd == "verify":
        tx = sys.argv[2] if len(sys.argv) > 2 else ""
        post = {"url": "https://example.com/post", "title": "Test", "source": "example.com"}
        res = verify_on_blockchain(post, tx, rpc)
        print(json.dumps(res, indent=2))
