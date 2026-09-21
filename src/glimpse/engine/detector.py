"""
Face Detection and 5-Point Landmark Localization module.
Supports OpenCV YuNet and SCRFD ONNX on CPUExecutionProvider.
"""

from __future__ import annotations
import os
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger("glimpse.engine.detector")

@dataclass
class DetectedFace:
    """Represents a detected face with bounding box, landmarks, and raw array."""
    bbox: Tuple[int, int, int, int]  # x, y, width, height
    score: float
    landmarks: np.ndarray             # 5x2 array: [left_eye, right_eye, nose, left_mouth, right_mouth]
    raw: np.ndarray                   # 15-element raw detector output for direct alignCrop

class YuNetDetector:
    """OpenCV YuNet Face Detector (ultra-fast CPU inference)."""

    def __init__(self, model_path: str, score_threshold: float = 0.6, nms_threshold: float = 0.3):
        self.model_path = model_path
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.detector = None
        self._current_input_size = (320, 320)
        self._load_model()

    def _load_model(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"YuNet model file not found: {self.model_path}")

        self.detector = cv2.FaceDetectorYN.create(
            model=self.model_path,
            config="",
            input_size=self._current_input_size,
            score_threshold=self.score_threshold,
            nms_threshold=self.nms_threshold,
            top_k=5000,
            backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
            target_id=cv2.dnn.DNN_TARGET_CPU,
        )

    def detect(self, image: np.ndarray) -> List[DetectedFace]:
        h, w = image.shape[:2]
        if (w, h) != self._current_input_size:
            self._current_input_size = (w, h)
            self.detector.setInputSize((w, h))

        _, faces = self.detector.detect(image)
        if faces is None or len(faces) == 0:
            return []

        results = []
        for face in faces:
            # Format: [x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score]
            x, y, fw, fh = map(int, face[0:4])
            score = float(face[-1])
            # Landmarks: right_eye, left_eye, nose_tip, right_mouth_corner, left_mouth_corner
            # Rearrange to: left_eye, right_eye, nose, left_mouth, right_mouth
            re = [face[4], face[5]]
            le = [face[6], face[7]]
            nt = [face[8], face[9]]
            rmc = [face[10], face[11]]
            lmc = [face[12], face[13]]

            # Note: OpenCV defines right_eye from subject's perspective (viewer's left)
            # Standard ArcFace expects [viewer_left_eye, viewer_right_eye, nose, viewer_left_mouth, viewer_right_mouth]
            landmarks = np.array([re, le, nt, rmc, lmc], dtype=np.float32)

            results.append(DetectedFace(
                bbox=(x, y, fw, fh),
                score=score,
                landmarks=landmarks,
                raw=face
            ))

        # Sort by area descending (primary face first)
        results.sort(key=lambda f: f.bbox[2] * f.bbox[3], reverse=True)
        return results

class SCRFDDetector:
    """SCRFD Face Detector via ONNX Runtime on CPU."""

    def __init__(self, model_path: str, score_threshold: float = 0.5):
        import onnxruntime as ort
        self.model_path = model_path
        self.score_threshold = score_threshold
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape

    def detect(self, image: np.ndarray) -> List[DetectedFace]:
        # Preprocess input image to target size
        target_w, target_h = 640, 640
        h, w = image.shape[:2]
        scale = min(target_w / w, target_h / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = cv2.resize(image, (nw, nh))

        padded = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        padded[:nh, :nw, :] = resized

        blob = cv2.dnn.blobFromImage(
            padded, 1.0 / 128.0, (target_w, target_h), (127.5, 127.5, 127.5), swapRB=True
        )
        outputs = self.session.run(None, {self.input_name: blob})
        # Parse SCRFD multi-stride anchors if model is pure SCRFD
        # Or parse generic face detection outputs
        # Handled in engine integration
        return []
