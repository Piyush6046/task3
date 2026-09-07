# Face Identification & Blockchain Verification Pipeline

> **HH Goa 2026 — Shortlisting Task 3**

A Python CLI pipeline that takes a face image as input, identifies matching content on the web/social media via reverse image search, and permanently records a tamper-evident hash of the discovered data on the Ethereum Sepolia blockchain.

---

## Pipeline Overview

```
Input Image
    │
    ▼
┌─────────────────────────────────────┐
│  STEP 1 — Face Detection            │
│  face_recognition (dlib) or OpenCV  │
│  → extracts 128-d face embedding    │
│  → saves face crop image            │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  STEP 2 — Reverse Image Search      │
│  SerpAPI Google Lens endpoint       │
│  → real-time web search             │
│  → returns matching social posts    │
│    (Instagram, Twitter, LinkedIn…)  │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  STEP 3 — Blockchain Upload         │
│  Ethereum Sepolia Testnet (web3.py) │
│  → SHA-256 hash of post metadata   │
│  → stores hash in tx data field     │
│  → returns Etherscan link           │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  STEP 4 — On-Chain Verification     │
│  → re-fetches tx from chain         │
│  → re-computes local hash           │
│  → compares → VERIFIED / FAILED     │
└─────────────────────────────────────┘
```

---

## Requirements

- **Python 3.9+**
- **cmake** and C++ build tools (for `face_recognition` / `dlib`)
  - Windows: install [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
  - macOS: `xcode-select --install`
  - Linux: `sudo apt install cmake build-essential`

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/face-blockchain-pipeline.git
cd face-blockchain-pipeline

# 2. Create a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

> **Note on `face_recognition`**: If installation fails on Windows (dlib build error), install the pre-built wheel first:
> ```bash
> pip install https://github.com/jloh02/dlib/releases/download/v19.22/dlib-19.22.0-cp310-cp310-win_amd64.whl
> pip install face-recognition
> ```
> Alternatively, the pipeline auto-falls back to `opencv-python` for face detection.

---

## Configuration

```bash
# Copy the sample env file
cp .env.sample .env
# Then open .env and fill in your API keys (see below)
```

### API Keys Required

| Variable | Where to get | Purpose |
|---|---|---|
| `SERPAPI_KEY` | [serpapi.com](https://serpapi.com) (free tier: 100 searches/mo) | Google Lens reverse image search |
| `INFURA_PROJECT_ID` | [infura.io](https://infura.io) (free tier) | Connect to Ethereum Sepolia RPC |
| `ETH_PRIVATE_KEY` | MetaMask → Export Private Key | Sign blockchain transactions |
| `ETH_WALLET_ADDRESS` | Your MetaMask wallet `0x...` address | Transaction sender |

> ⚠️ **Use a Sepolia TESTNET wallet only** — never use a wallet with real ETH funds.
> Get free Sepolia ETH from: [sepoliafaucet.com](https://sepoliafaucet.com)

---

## Usage

### Full pipeline (recommended)
```bash
python pipeline.py --image path/to/person.jpg
```

### Test without blockchain (faster, no gas needed)
```bash
python pipeline.py --image path/to/person.jpg --no-blockchain
```

### Re-verify a previous run
```bash
python pipeline.py --verify-only output/pipeline_result_20260907_123456.json
```

### Search only (using a pre-cropped face image)
```bash
python pipeline.py --search-only output/face_crop.png
```

---

## Output

All outputs are saved in the `output/` directory:

| File | Description |
|---|---|
| `output/face_crop.png` | Detected and cropped face |
| `output/pipeline_result_<timestamp>.json` | Full pipeline result (hashes, tx, verification) |

### Example terminal output

```
──────────────────────────────────────────────────────────
  STEP 1 — Face Detection & Encoding
──────────────────────────────────────────────────────────
✅  Face detected and encoded. 1 face(s) found in image.
ℹ️   Face crop saved → output/face_crop.png
  Embedding hash : a3f8c9d...

──────────────────────────────────────────────────────────
  STEP 2 — Reverse Image Search (Social Media)
──────────────────────────────────────────────────────────
✅  Found 3 social media result(s). Top match: https://www.instagram.com/p/...
ℹ️   Top match title  : John Doe on Instagram
ℹ️   Top match URL    : https://www.instagram.com/p/ABC123/
ℹ️   Source           : instagram.com

──────────────────────────────────────────────────────────
  STEP 3 — Blockchain Upload (Ethereum Sepolia Testnet)
──────────────────────────────────────────────────────────
✅  On-chain record created! Block #6421809
ℹ️   Data hash  : 7b2c4f...
ℹ️   Tx hash    : 0xabc123...
✅  Etherscan  : https://sepolia.etherscan.io/tx/0xabc123...

──────────────────────────────────────────────────────────
  STEP 4 — On-Chain Verification
──────────────────────────────────────────────────────────
✅  VERIFIED — Hash matches on-chain record in block #6421809.
  Etherscan : https://sepolia.etherscan.io/tx/0xabc123...
```

---

## Blockchain Details

| Property | Value |
|---|---|
| **Chain** | Ethereum Sepolia Testnet |
| **Chain ID** | 11155111 |
| **Explorer** | [sepolia.etherscan.io](https://sepolia.etherscan.io) |
| **Data stored** | SHA-256 of `{url, title, source, search_url}` |
| **Storage method** | Raw ETH self-transfer; hash in `data`/`input` field |
| **Re-verification** | Re-hash locally, compare with `tx.input` field on chain |

### Why raw transaction (not a smart contract)?

Using the `data` field of a plain ETH transfer is simpler, cheaper, and more transparent than deploying a Solidity contract — anyone can read and verify the data directly on Etherscan with zero ABI decoding needed.

---

## Project Structure

```
face-blockchain-pipeline/
├── pipeline.py              # Main CLI (run this)
├── face_detector.py         # Step 1: face detection + encoding
├── web_searcher.py          # Step 2: SerpAPI reverse image search
├── blockchain_verifier.py   # Steps 3+4: blockchain upload + verification
├── utils.py                 # Shared helpers (hashing, logging, colors)
├── requirements.txt
├── .env.sample              # Copy to .env and fill in keys
└── output/                  # Auto-created: face crops, result JSONs
```

---

## Known Limitations

- `face_recognition` / `dlib` can be tricky to install on Windows — use the pre-built wheel or OpenCV fallback.
- SerpAPI free tier: 100 Google Lens searches per month.
- The reverse image search works best for public figures or images already indexed on the web. Private/new faces may return no social media results.
- Sepolia testnet tx finality: ~12 seconds.
- No live website — this is a CLI-only pipeline.

---

## Dependencies

- [`face_recognition`](https://github.com/ageitgey/face_recognition) — dlib-based face detection
- [`opencv-python`](https://pypi.org/project/opencv-python/) — fallback face detection
- [`web3.py`](https://web3py.readthedocs.io/) — Ethereum interaction
- [`serpapi`](https://serpapi.com/) — Google Lens reverse image search
- [`requests`](https://requests.readthedocs.io/), [`Pillow`](https://pillow.readthedocs.io/), [`python-dotenv`](https://pypi.org/project/python-dotenv/)
