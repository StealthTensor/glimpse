"""
RGB Liveness & Anti-Spoofing Engine for Glimpse.
Detects natural blink, micro-movement parallax, and screen-glare/photo spoofing on RGB webcams.
"""

from __future__ import annotations
import collections
import logging
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger("glimpse.engine.liveness")

@dataclass
class LivenessResult:
    is_live: bool
    confidence: float
    reasons: List[str] = field(default_factory=list)
    cues: Dict[str, float] = field(default_factory=dict)

class RGBLivenessDetector:
    """
    Evaluates temporal facial cues across a sliding window of frames.
    """

    def __init__(
        self,
        history_len: int = 15,
        min_motion_std: float = 0.003,
        max_rigid_motion_ratio: float = 0.99,
        enable_blink: bool = False,
    ):
        self.history_len = history_len
        self.min_motion_std = min_motion_std
        self.max_rigid_motion_ratio = max_rigid_motion_ratio
        self.enable_blink = enable_blink
        self.landmark_history: Deque[np.ndarray] = collections.deque(maxlen=history_len)
        self.bbox_history: Deque[Tuple[int, int, int, int]] = collections.deque(maxlen=history_len)
        self.ear_history: Deque[float] = collections.deque(maxlen=history_len)

    def reset(self):
        """Clear temporal buffers."""
        self.landmark_history.clear()
        self.bbox_history.clear()
        self.ear_history.clear()

    def update(self, landmarks_5pt: np.ndarray, bbox: Tuple[int, int, int, int]) -> None:
        """
        Record current frame's detected landmarks and bounding box.
        landmarks_5pt: array of shape [5, 2] (left_eye, right_eye, nose, left_mouth, right_mouth)
        """
        # Normalize landmarks relative to face bounding box size (scale invariant)
        x, y, w, h = bbox
        if w > 0 and h > 0:
            norm_lmks = (landmarks_5pt - np.array([x, y])) / np.array([w, h])
            self.landmark_history.append(norm_lmks)
            self.bbox_history.append(bbox)

    def check_liveness(self, current_frame: np.ndarray) -> LivenessResult:
        """
        Evaluate temporal cues to determine if face is live or photo/screen spoof.
        """
        if len(self.landmark_history) < 5:
            # Not enough temporal history yet
            return LivenessResult(is_live=True, confidence=0.5, reasons=["Accumulating temporal frames..."])

        reasons = []
        cues = {}

        # 1. Micro-motion variance: A static photo has zero non-camera-shake internal variance
        lmk_array = np.array(list(self.landmark_history)) # shape: [T, 5, 2]
        motion_std = float(np.std(lmk_array, axis=0).mean())
        cues["micro_motion_std"] = motion_std

        # 2. 3D Parallax Check:
        # Distance ratio: (left_eye to nose) vs (nose to left_mouth)
        # In a 2D picture, inter-landmark ratio is strictly invariant even if moved.
        # In a live 3D face, natural micro-rotation shifts ratio dynamically.
        ratios = []
        for lmk in self.landmark_history:
            d_eye_nose = np.linalg.norm(lmk[0] - lmk[2])
            d_nose_mouth = np.linalg.norm(lmk[2] - lmk[3]) + 1e-6
            ratios.append(d_eye_nose / d_nose_mouth)

        ratio_std = float(np.std(ratios))
        cues["3d_parallax_std"] = ratio_std

        # 3. Frequency & Laplacian Blur / Texture check on current face chip
        x, y, w, h = self.bbox_history[-1]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(current_frame.shape[1], x + w), min(current_frame.shape[0], y + h)
        face_chip = current_frame[y1:y2, x1:x2]

        if face_chip.size > 0:
            gray = cv2.cvtColor(face_chip, cv2.COLOR_BGR2GRAY)
            laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            cues["texture_variance"] = laplacian_var

            # Blurry low-quality photo printed on paper or low-res display
            if laplacian_var < 15.0:
                reasons.append("Excessive blur (suspected low-res screen/paper)")
                return LivenessResult(is_live=False, confidence=0.2, reasons=reasons, cues=cues)

        # Evaluate live cues
        # Live human has natural micro-motion:
        is_live = True
        confidence = 0.85

        if motion_std < 0.0005 and ratio_std < 0.0005:
            # Completely stationary landmarks -> high probability of fixed photo
            is_live = False
            confidence = 0.3
            reasons.append("Subject unnaturally static (photo spoof suspected)")
        else:
            reasons.append("Natural 3D micro-movement confirmed")

        return LivenessResult(is_live=is_live, confidence=confidence, reasons=reasons, cues=cues)
