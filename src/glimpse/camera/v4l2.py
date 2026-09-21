"""
V4L2 Camera Capture Module for Glimpse.
Supports hardware capture via Linux Video4Linux2 (/dev/video0).
Ensures safe release and warm-up frame discarding.
"""

from __future__ import annotations
import time
import logging
from typing import Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger("glimpse.camera")

class V4L2Camera:
    """Manages V4L2 webcam capture lifecycle."""

    def __init__(
        self,
        device_index: int = 0,
        device_path: Optional[str] = None,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        warmup_frames: int = 3,
    ):
        self.device_index = device_index
        self.device_path = device_path or f"/dev/video{device_index}"
        self.width = width
        self.height = height
        self.fps = fps
        self.warmup_frames = warmup_frames
        self.cap: Optional[cv2.VideoCapture] = None

    def open(self) -> bool:
        """Open the camera device using V4L2 backend."""
        if self.cap is not None and self.cap.isOpened():
            return True

        logger.debug(f"Opening camera: {self.device_path} (idx: {self.device_index})")
        # Try device index with V4L2 backend
        self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            # Fallback to default backend
            self.cap = cv2.VideoCapture(self.device_index)

        if not self.cap.isOpened():
            logger.error(f"Failed to open video capture on {self.device_path}")
            return False

        # Apply camera parameters
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        # Try setting fourcc to MJPG for faster capture if supported
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        # Flush initial warm-up frames (auto-exposure/white-balance settling)
        for _ in range(self.warmup_frames):
            ret, _ = self.cap.read()
            if not ret:
                break
            time.sleep(0.02)

        logger.debug("Camera successfully opened and calibrated.")
        return True

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read a single BGR frame from the camera."""
        if self.cap is None or not self.cap.isOpened():
            return False, None

        ret, frame = self.cap.read()
        if not ret or frame is None:
            return False, None

        return True, frame

    def release(self) -> None:
        """Immediately release hardware handle so camera indicator LED turns off."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as e:
                logger.warning(f"Error releasing camera: {e}")
            finally:
                self.cap = None
                logger.debug("Camera released.")

    def __enter__(self) -> V4L2Camera:
        if not self.open():
            raise RuntimeError(f"Could not open camera device {self.device_path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
