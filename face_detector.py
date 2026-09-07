"""
Step 1 – Face Detection & Encoding
Detects a face in the input image, encodes it as a 128-d embedding,
and saves the cropped face for use in the reverse-image search step.
"""

import os
import sys
import json
import hashlib
import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def detect_and_encode(image_path: str, output_dir: str = "output") -> dict:
    """
    Detect the primary face in *image_path*, compute its 128-d embedding,
    save a cropped face image, and return a result dict.

    Returns
    -------
    dict with keys:
        face_found    : bool
        embedding     : list[float] | None
        embedding_hash: str | None   (SHA-256 of the embedding bytes)
        face_crop_path: str | None   (path to saved cropped face PNG)
        num_faces     : int
        message       : str
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    result = {
        "face_found": False,
        "embedding": None,
        "embedding_hash": None,
        "face_crop_path": None,
        "num_faces": 0,
        "message": "",
    }

    if not os.path.exists(image_path):
        result["message"] = f"Image not found: {image_path}"
        logger.error(result["message"])
        return result

    logger.info(f"Loading image: {image_path}")

    # ------------------------------------------------------------------ #
    # Try face_recognition first (dlib-based, most accurate)              #
    # Fall back to OpenCV Haar cascade if face_recognition is unavailable #
    # ------------------------------------------------------------------ #
    try:
        import face_recognition  # type: ignore

        img_array = face_recognition.load_image_file(image_path)
        face_locations = face_recognition.face_locations(img_array, model="hog")
        result["num_faces"] = len(face_locations)

        if not face_locations:
            result["message"] = "No faces detected in the image."
            logger.warning(result["message"])
            return result

        # Use the first (largest) face
        top, right, bottom, left = face_locations[0]
        logger.info(f"Face detected at (top={top}, right={right}, bottom={bottom}, left={left})")

        # Compute embedding
        encodings = face_recognition.face_encodings(img_array, [face_locations[0]])
        if not encodings:
            result["message"] = "Face located but encoding failed."
            logger.error(result["message"])
            return result

        embedding = encodings[0].tolist()

        # Save cropped face
        pil_img = Image.open(image_path).convert("RGB")
        # Add padding
        h, w = img_array.shape[:2]
        pad = 20
        crop_top    = max(0, top - pad)
        crop_bottom = min(h, bottom + pad)
        crop_left   = max(0, left - pad)
        crop_right  = min(w, right + pad)
        face_crop = pil_img.crop((crop_left, crop_top, crop_right, crop_bottom))
        crop_path = os.path.join(output_dir, "face_crop.png")
        face_crop.save(crop_path)
        logger.info(f"Face crop saved → {crop_path}")

        # SHA-256 of the embedding (128 floats → bytes)
        emb_bytes = np.array(embedding, dtype=np.float64).tobytes()
        emb_hash = hashlib.sha256(emb_bytes).hexdigest()

        result.update(
            face_found=True,
            embedding=embedding,
            embedding_hash=emb_hash,
            face_crop_path=os.path.abspath(crop_path),
            message=f"Face detected and encoded. {len(face_locations)} face(s) found in image.",
        )
        return result

    except ImportError:
        logger.warning("face_recognition not available — falling back to OpenCV.")

    # ------------------------------------------------------------------ #
    # OpenCV fallback                                                      #
    # ------------------------------------------------------------------ #
    try:
        import cv2  # type: ignore

        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            result["message"] = f"OpenCV could not read image: {image_path}"
            logger.error(result["message"])
            return result

        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # Use bundled Haar cascade
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        result["num_faces"] = len(faces)

        if len(faces) == 0:
            result["message"] = "No faces detected in the image (OpenCV fallback)."
            logger.warning(result["message"])
            return result

        x, y, w, h = faces[0]
        logger.info(f"Face detected at x={x}, y={y}, w={w}, h={h}")

        # Crop and save
        pad = 20
        img_h, img_w = img_bgr.shape[:2]
        cx1 = max(0, x - pad)
        cy1 = max(0, y - pad)
        cx2 = min(img_w, x + w + pad)
        cy2 = min(img_h, y + h + pad)
        face_crop = img_bgr[cy1:cy2, cx1:cx2]
        crop_path = os.path.join(output_dir, "face_crop.png")
        cv2.imwrite(crop_path, face_crop)
        logger.info(f"Face crop saved → {crop_path}")

        # Build a simple "embedding" from the pixel histogram (fallback)
        face_gray = gray[cy1:cy2, cx1:cx2]
        hist = cv2.calcHist([face_gray], [0], None, [128], [0, 256]).flatten()
        hist_norm = (hist / (hist.sum() + 1e-9)).tolist()

        emb_bytes = np.array(hist_norm, dtype=np.float64).tobytes()
        emb_hash = hashlib.sha256(emb_bytes).hexdigest()

        result.update(
            face_found=True,
            embedding=hist_norm,
            embedding_hash=emb_hash,
            face_crop_path=os.path.abspath(crop_path),
            message=f"Face detected (OpenCV). {len(faces)} face(s) found in image.",
        )
        return result

    except ImportError:
        result["message"] = (
            "Neither face_recognition nor OpenCV is installed. "
            "Install at least one: pip install face-recognition  OR  pip install opencv-python"
        )
        logger.error(result["message"])
        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    img = sys.argv[1] if len(sys.argv) > 1 else "sample_face.jpg"
    res = detect_and_encode(img)
    print(json.dumps(res, indent=2, default=str))
