"""
Authentication Session State Machine for Glimpse Daemon.
Manages single-session hardware locking, policy enforcement, night illumination, and timeout guarantees.
"""

from __future__ import annotations
import time
import logging
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, List
import numpy as np
import cv2

from glimpse.camera.v4l2 import V4L2Camera
from glimpse.engine.detector import YuNetDetector
from glimpse.engine.embedder import FaceEmbedder
from glimpse.engine.matcher import BiometricMatcher
from glimpse.engine.liveness import RGBLivenessDetector, LivenessResult
from glimpse.storage.vault import BiometricVault
from glimpse.daemon.backlight import BacklightManager

logger = logging.getLogger("glimpse.daemon.session")

class SessionState(Enum):
    IDLE = auto()
    SCANNING = auto()
    SUCCESS = auto()
    FAILURE = auto()

@dataclass
class AuthResult:
    success: bool
    username: str
    similarity: float = 0.0
    reason: str = ""
    duration_ms: float = 0.0

class AuthSession:
    """Coordinates camera capture, detection, liveness, and matching for one auth request."""

    def __init__(
        self,
        detector: YuNetDetector,
        embedder: FaceEmbedder,
        matcher: BiometricMatcher,
        vault: BiometricVault,
        device_index: int = 0,
    ):
        self.detector = detector
        self.embedder = embedder
        self.matcher = matcher
        self.vault = vault
        self.device_index = device_index
        self.state = SessionState.IDLE
        self.backlight = BacklightManager()

    def authenticate(
        self,
        username: str,
        timeout_seconds: float = 2.5,
        min_similarity: Optional[float] = None,
        liveness_required: bool = True,
        event_callback=None,
    ) -> AuthResult:
        """
        Execute authentication loop for target user within timeout.
        event_callback(event_name: str, payload: dict) -> called to notify UI.
        """
        start_time = time.perf_counter()
        templates = self.vault.load_templates(username)
        if not templates:
            logger.warning(f"No enrolled templates for user '{username}'")
            return AuthResult(
                success=False,
                username=username,
                reason="no_enrolled_templates",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        self.state = SessionState.SCANNING
        if event_callback:
            event_callback("scan_started", {"username": username, "timeout": timeout_seconds})

        cam = V4L2Camera(device_index=self.device_index, width=640, height=480)
        if not cam.open():
            self.state = SessionState.FAILURE
            if event_callback:
                event_callback("auth_failure", {"username": username, "reason": "camera_busy"})
            return AuthResult(
                success=False,
                username=username,
                reason="camera_unavailable",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        liveness = RGBLivenessDetector()
        best_score = 0.0
        verified = False
        fail_reason = "timeout"
        night_mode_triggered = False
        backlight_boosted = False
        luminance_threshold = 45.0

        effective_threshold = min_similarity if min_similarity is not None else self.matcher.threshold

        consecutive_matches = 0
        required_consecutive = 3  # Temporal anti-impostor filter (requires 3 consecutive frames)

        try:
            while (time.perf_counter() - start_time) < timeout_seconds:
                ret, frame = cam.read_frame()
                if not ret or frame is None:
                    continue

                # Pitch Black / Low Light Detection: check mean frame luminance
                mean_lum = float(np.mean(frame))
                if mean_lum < luminance_threshold and not night_mode_triggered:
                    night_mode_triggered = True
                    logger.info(f"Low ambient luminance detected ({mean_lum:.1f} < {luminance_threshold}). Boosting screen backlight.")
                    self.backlight.boost()
                    backlight_boosted = True
                    if event_callback:
                        event_callback("night_mode_on", {"luminance": mean_lum})

                faces = self.detector.detect(frame)
                if not faces:
                    consecutive_matches = 0
                    continue

                primary = faces[0]
                liveness.update(primary.landmarks, primary.bbox)

                # Extract embedding
                aligned = self.embedder.align_and_crop(frame, primary.raw)
                feat = self.embedder.extract(aligned)

                is_match, score = self.matcher.match(feat, templates)
                if score > best_score:
                    best_score = score

                if score >= effective_threshold:
                    if liveness_required:
                        live_res = liveness.check_liveness(frame)
                        is_live = live_res.is_live
                    else:
                        is_live = True

                    if is_live:
                        consecutive_matches += 1
                        logger.debug(f"Matching frame {consecutive_matches}/{required_consecutive} (score={score:.4f} >= {effective_threshold:.4f})")
                        if consecutive_matches >= required_consecutive:
                            verified = True
                            self.state = SessionState.SUCCESS
                            if event_callback:
                                event_callback("auth_success", {
                                    "username": username,
                                    "similarity": best_score,
                                    "duration_ms": (time.perf_counter() - start_time) * 1000.0,
                                })
                            break
                    else:
                        consecutive_matches = 0
                        fail_reason = "liveness_failed"
                        logger.debug(f"Face matched ({score:.3f}) but liveness rejected: {live_res.reasons}")
                else:
                    consecutive_matches = 0
        finally:
            # Guarantee immediate camera release and backlight restoration
            cam.release()
            if backlight_boosted:
                self.backlight.restore()
            if event_callback and night_mode_triggered:
                event_callback("night_mode_off", {})

        duration = (time.perf_counter() - start_time) * 1000.0

        if verified:
            return AuthResult(
                success=True,
                username=username,
                similarity=best_score,
                reason="verified",
                duration_ms=duration,
            )
        else:
            self.state = SessionState.FAILURE
            if event_callback:
                event_callback("auth_failure", {
                    "username": username,
                    "reason": fail_reason,
                    "similarity": best_score,
                    "duration_ms": duration,
                })
            return AuthResult(
                success=False,
                username=username,
                similarity=best_score,
                reason=fail_reason,
                duration_ms=duration,
            )
