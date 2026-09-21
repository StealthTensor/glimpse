"""
Face Embedding module for Glimpse.
Supports 512-dimensional ArcFace / MobileFaceNet (InsightFace ONNX) and 128-D SFace on CPU.
Produces unit-normalized biometric feature vectors optimized with AVX2 CPU execution.
"""

from __future__ import annotations
import os
import logging
from typing import Optional, Union
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort

from glimpse.engine.aligner import align_face_112

logger = logging.getLogger("glimpse.engine.embedder")


class FaceEmbedder:
    """Extracts 512-D or 128-D biometric embedding vectors on CPU."""

    def __init__(self, model_path: Optional[str] = None):
        root_dir = Path(__file__).resolve().parents[3]
        default_512 = str(root_dir / "models" / "w600k_mbf.onnx")
        default_sface = str(root_dir / "models" / "face_recognition_sface_2021dec.onnx")

        if model_path:
            self.model_path = model_path
        elif os.path.exists(default_512):
            self.model_path = default_512
        else:
            self.model_path = default_sface

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Embedding model not found: {self.model_path}")

        self.is_onnx_arcface = "sface" not in os.path.basename(self.model_path).lower()

        if self.is_onnx_arcface:
            # 512-D ArcFace ONNX Model
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self.session = ort.InferenceSession(self.model_path, opts, providers=["CPUExecutionProvider"])
            self.input_name = self.session.get_inputs()[0].name
            self.vector_dim = 512
            logger.info(f"Loaded 512-D ArcFace model from {self.model_path} on CPU.")
        else:
            # Legacy 128-D SFace Model
            self.recognizer = cv2.FaceRecognizerSF.create(self.model_path, "")
            self.vector_dim = 128
            logger.info(f"Loaded 128-D SFace model from {self.model_path} on CPU.")

    def align_and_crop(self, frame: np.ndarray, face_data: np.ndarray) -> np.ndarray:
        """
        Align and crop face using 5 facial landmarks to standard 112x112 chip.
        face_data: 15-element raw array or 5x2 landmarks array.
        """
        if self.is_onnx_arcface:
            # Extract 5x2 landmarks
            if face_data.ndim == 1 and len(face_data) >= 14:
                lmks = face_data[4:14].reshape(5, 2)
            elif face_data.ndim == 2 and face_data.shape == (5, 2):
                lmks = face_data
            else:
                lmks = face_data.reshape(-1, 2)[:5]
            return align_face_112(frame, lmks)
        else:
            face = face_data.reshape(1, -1) if face_data.ndim == 1 else face_data
            return self.recognizer.alignCrop(frame, face)

    def extract(self, aligned_face_chip: np.ndarray) -> np.ndarray:
        """
        Extract normalized biometric feature vector from 112x112 aligned face chip.
        Returns: 1D numpy float32 vector with L2 norm = 1.0.
        """
        if self.is_onnx_arcface:
            # Preprocess for ArcFace / MobileFaceNet:
            # Resize if necessary to 112x112
            if aligned_face_chip.shape[:2] != (112, 112):
                aligned_face_chip = cv2.resize(aligned_face_chip, (112, 112), interpolation=cv2.INTER_LINEAR)
            # BGR -> RGB
            rgb = cv2.cvtColor(aligned_face_chip, cv2.COLOR_BGR2RGB)
            # Normalize to [-1, 1] range: (pixel - 127.5) / 128.0
            blob = ((rgb.astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None, ...]
            raw_feat = self.session.run(None, {self.input_name: blob})[0][0]
            # L2 normalize
            norm = np.linalg.norm(raw_feat)
            if norm > 1e-6:
                feat = raw_feat / norm
            else:
                feat = raw_feat
            return feat.astype(np.float32)
        else:
            feat = self.recognizer.feature(aligned_face_chip).flatten().astype(np.float32)
            norm = np.linalg.norm(feat)
            if norm > 1e-6:
                feat = feat / norm
            return feat

    def match(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """
        Compute cosine similarity between two feature vectors.
        """
        v1 = np.asarray(feat1, dtype=np.float32).flatten()
        v2 = np.asarray(feat2, dtype=np.float32).flatten()
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        return float(np.dot(v1, v2) / (n1 * n2))
