"""
Face Alignment module for ArcFace.
Computes similarity transform using 5 facial landmarks and crops to 112x112 chip.
"""

from __future__ import annotations
import cv2
import numpy as np

# Standard reference points for 112x112 ArcFace alignment
ARCFACE_REFERENCE_POINTS = np.array([
    [38.2946, 51.6963],  # left eye
    [73.5318, 51.5014],  # right eye
    [56.0252, 71.7366],  # nose
    [41.5493, 92.3655],  # left mouth corner
    [70.7299, 92.2041]   # right mouth corner
], dtype=np.float32)

def align_face_112(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """
    Align face from 5 landmarks (shape: [5, 2]) to standard 112x112 chip.
    """
    landmarks = np.asarray(landmarks, dtype=np.float32)
    assert landmarks.shape == (5, 2), f"Expected 5x2 landmarks, got {landmarks.shape}"

    # Estimate similarity transform (rotation, translation, uniform scale)
    tfm, _ = cv2.estimateAffinePartial2D(landmarks, ARCFACE_REFERENCE_POINTS, method=cv2.LMEDS)
    if tfm is None:
        # Fallback to simple transformation
        tfm = cv2.getAffineTransform(landmarks[:3], ARCFACE_REFERENCE_POINTS[:3])

    aligned = cv2.warpAffine(
        image,
        tfm,
        (112, 112),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0)
    )
    return aligned
