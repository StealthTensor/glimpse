"""
Glimpse Live Diagnostic & Model Verification Studio.
Provides real-time camera feed with facial landmark overlays, biometric embedding metrics,
liveness analysis, low-light luminance checks, and configurable similarity threshold testing.
"""

from __future__ import annotations
import os
import sys
import time
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import cv2
import numpy as np

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QRectF, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont

from glimpse.storage.vault import BiometricVault
from glimpse.engine.detector import YuNetDetector, DetectedFace
from glimpse.engine.embedder import FaceEmbedder
from glimpse.engine.matcher import BiometricMatcher
from glimpse.engine.liveness import RGBLivenessDetector, LivenessResult
from glimpse.ui.illuminator import ScreenIlluminator


class DiagnosticWorker(QThread):
    """
    Background worker thread running OpenCV camera capture and the Glimpse AI pipeline.
    Emits raw frames, detection results, biometric similarity, liveness, and latency timings.
    """
    frame_processed = pyqtSignal(np.ndarray, dict)

    def __init__(self, camera_idx: int = 0, target_user: str = "stealthtensor"):
        super().__init__()
        self.camera_idx = camera_idx
        self.target_user = target_user
        self.running = True
        self.test_threshold = 0.450

        # Load models
        root_dir = Path(__file__).resolve().parents[3]
        det_model = str(root_dir / "models" / "face_detection_yunet_2023mar.onnx")
        emb_model = str(root_dir / "models" / "w600k_mbf.onnx")

        self.detector = YuNetDetector(model_path=det_model, score_threshold=0.55)
        self.embedder = FaceEmbedder(model_path=emb_model)
        self.matcher = BiometricMatcher(threshold=self.test_threshold)
        self.liveness = RGBLivenessDetector()

        # Vault & templates
        self.vault = BiometricVault()
        self.enrolled_templates: List[np.ndarray] = self.vault.load_templates(self.target_user)

    def set_target_user(self, username: str):
        self.target_user = username
        self.enrolled_templates = self.vault.load_templates(username)
        self.liveness.reset()

    def set_threshold(self, thresh: float):
        self.test_threshold = thresh
        self.matcher.threshold = thresh

    def stop(self):
        self.running = False
        self.wait(1000)

    def run(self):
        cap = cv2.VideoCapture(self.camera_idx)
        if not cap.isOpened():
            print(f"[ERROR] Could not open camera {self.camera_idx}")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        prev_time = time.perf_counter()

        while self.running:
            t0 = time.perf_counter()
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            t_cap = (time.perf_counter() - t0) * 1000.0

            # 1. Luminance check
            mean_lum = float(np.mean(frame))

            # 2. Face Detection
            t_det0 = time.perf_counter()
            faces = self.detector.detect(frame)
            t_det = (time.perf_counter() - t_det0) * 1000.0

            primary_face: Optional[DetectedFace] = faces[0] if faces else None
            t_emb = 0.0
            t_match = 0.0
            best_score = 0.0
            is_match = False
            top_idx = -1
            candidate_norm = 0.0
            liveness_res = None

            if primary_face:
                # 3. Liveness update
                self.liveness.update(primary_face.landmarks, primary_face.bbox)
                liveness_res = self.liveness.check_liveness(frame)

                # 4. Feature extraction
                t_emb0 = time.perf_counter()
                aligned = self.embedder.align_and_crop(frame, primary_face.raw)
                feat = self.embedder.extract(aligned)
                t_emb = (time.perf_counter() - t_emb0) * 1000.0
                candidate_norm = float(np.linalg.norm(feat))

                # 5. Matching against enrolled templates
                t_match0 = time.perf_counter()
                if self.enrolled_templates:
                    scores = [self.matcher.cosine_similarity(feat, t) for t in self.enrolled_templates]
                    if scores:
                        best_score = max(scores)
                        top_idx = int(np.argmax(scores))
                        is_match = best_score >= self.test_threshold
                t_match = (time.perf_counter() - t_match0) * 1000.0
            else:
                self.liveness.reset()

            t_total = (time.perf_counter() - t0) * 1000.0
            fps = 1.0 / max(1e-5, (time.perf_counter() - prev_time))
            prev_time = time.perf_counter()

            metrics = {
                "fps": fps,
                "luminance": mean_lum,
                "is_night_mode": mean_lum < 38.0,
                "faces_count": len(faces),
                "has_face": primary_face is not None,
                "bbox": primary_face.bbox if primary_face else None,
                "landmarks": primary_face.landmarks.tolist() if primary_face else None,
                "det_score": primary_face.score if primary_face else 0.0,
                "similarity": best_score,
                "is_match": is_match,
                "top_template_idx": top_idx,
                "enrolled_count": len(self.enrolled_templates),
                "threshold": self.test_threshold,
                "margin": best_score - self.test_threshold,
                "candidate_norm": candidate_norm,
                "liveness_is_live": liveness_res.is_live if liveness_res else None,
                "liveness_confidence": liveness_res.confidence if liveness_res else 0.0,
                "liveness_cues": liveness_res.cues if liveness_res else {},
                "liveness_reasons": liveness_res.reasons if liveness_res else [],
                "timing_cap_ms": t_cap,
                "timing_det_ms": t_det,
                "timing_emb_ms": t_emb,
                "timing_match_ms": t_match,
                "timing_total_ms": t_total,
                "target_user": self.target_user,
            }

            self.frame_processed.emit(frame, metrics)

        cap.release()


class VideoWidget(QtWidgets.QWidget):
    """Renders the live video feed with smooth hardware-accelerated bounding box and landmark overlays."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(640, 480)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.current_pixmap: Optional[QPixmap] = None
        self.metrics: Dict[str, Any] = {}

    def update_frame(self, frame: np.ndarray, metrics: dict):
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        # OpenCV BGR -> RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self.current_pixmap = QPixmap.fromImage(qimg)
        self.metrics = metrics
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Draw deep dark background
        painter.fillRect(self.rect(), QColor(10, 12, 16))

        if not self.current_pixmap:
            painter.setPen(QColor(120, 130, 145))
            painter.setFont(QFont("Inter, sans-serif", 13))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Waiting for camera feed...")
            return

        # Scale aspect-fit
        pw = self.width()
        ph = self.height()
        scaled = self.current_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        ox = (pw - scaled.width()) // 2
        oy = (ph - scaled.height()) // 2
        painter.drawPixmap(ox, oy, scaled)

        scale_x = scaled.width() / float(self.current_pixmap.width())
        scale_y = scaled.height() / float(self.current_pixmap.height())

        # Render Overlays if face detected
        if self.metrics.get("has_face") and self.metrics.get("bbox"):
            x, y, w, h = self.metrics["bbox"]
            rx = ox + x * scale_x
            ry = oy + y * scale_y
            rw = w * scale_x
            rh = h * scale_y

            is_match = self.metrics.get("is_match", False)
            sim = self.metrics.get("similarity", 0.0)

            # Color scheme: Neon Emerald if verified match, Crimson if unverified/stranger
            if is_match:
                box_color = QColor(0, 245, 140) # Bright Apple Emerald
                fill_color = QColor(0, 245, 140, 30)
            else:
                box_color = QColor(255, 65, 85) # Electric Red
                fill_color = QColor(255, 65, 85, 30)

            # Bounding Box
            painter.setPen(QPen(box_color, 2, Qt.PenStyle.SolidLine))
            painter.setBrush(QBrush(fill_color))
            painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 10.0, 10.0)

            # Corner brackets for tech aesthetic
            bracket_len = min(20.0, rw * 0.2)
            b_pen = QPen(box_color, 3.5)
            painter.setPen(b_pen)
            # Top-left
            painter.drawLine(QPointF(rx, ry + bracket_len), QPointF(rx, ry))
            painter.drawLine(QPointF(rx, ry), QPointF(rx + bracket_len, ry))
            # Top-right
            painter.drawLine(QPointF(rx + rw - bracket_len, ry), QPointF(rx + rw, ry))
            painter.drawLine(QPointF(rx + rw, ry), QPointF(rx + rw, ry + bracket_len))
            # Bottom-left
            painter.drawLine(QPointF(rx, ry + rh - bracket_len), QPointF(rx, ry + rh))
            painter.drawLine(QPointF(rx, ry + rh), QPointF(rx + bracket_len, ry + rh))
            # Bottom-right
            painter.drawLine(QPointF(rx + rw - bracket_len, ry + rh), QPointF(rx + rw, ry + rh))
            painter.drawLine(QPointF(rx + rw, ry + rh), QPointF(rx + rw, ry + rh - bracket_len))

            # 5 Facial Landmarks
            lmks = self.metrics.get("landmarks")
            if lmks and len(lmks) >= 5:
                # 0: Left Eye (Cyan), 1: Right Eye (Cyan), 2: Nose (Gold), 3: Left Mouth (Magenta), 4: Right Mouth (Magenta)
                colors = [
                    QColor(0, 220, 255), QColor(0, 220, 255),
                    QColor(255, 215, 0),
                    QColor(255, 80, 200), QColor(255, 80, 200)
                ]
                for idx, pt in enumerate(lmks):
                    lx = ox + pt[0] * scale_x
                    ly = oy + pt[1] * scale_y
                    painter.setPen(Qt.PenStyle.NoPen)
                    # Outer glow
                    glow_c = QColor(colors[idx])
                    glow_c.setAlpha(120)
                    painter.setBrush(QBrush(glow_c))
                    painter.drawEllipse(QPointF(lx, ly), 5.5, 5.5)
                    # Core dot
                    painter.setBrush(QBrush(colors[idx]))
                    painter.drawEllipse(QPointF(lx, ly), 2.5, 2.5)

            # Top label badge on bounding box
            badge_text = f"SIM: {sim:.3f} | {'VERIFIED' if is_match else 'STRANGER'}"
            painter.setFont(QFont("JetBrains Mono, monospace", 9, QFont.Weight.Bold))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(badge_text) + 16
            th = 22
            bx = rx
            by = max(float(oy), ry - th - 4)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(box_color))
            painter.drawRoundedRect(QRectF(bx, by, tw, th), 4, 4)

            painter.setPen(QColor(0, 0, 0))
            painter.drawText(QRectF(bx, by, tw, th), Qt.AlignmentFlag.AlignCenter, badge_text)

        # HUD Top-Left Overlay
        fps = self.metrics.get("fps", 0.0)
        tot_ms = self.metrics.get("timing_total_ms", 0.0)
        lum = self.metrics.get("luminance", 0.0)
        is_night = self.metrics.get("is_night_mode", False)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 170)))
        painter.drawRoundedRect(QRectF(ox + 12, oy + 12, 190, 68), 8, 8)

        painter.setFont(QFont("JetBrains Mono, monospace", 9))
        painter.setPen(QColor(180, 200, 220))
        painter.drawText(ox + 22, oy + 32, f"FPS: {fps:.1f} ({tot_ms:.1f}ms)")
        painter.drawText(ox + 22, oy + 50, f"Luminance: {lum:.1f} / 255")

        if is_night:
            painter.setPen(QColor(255, 180, 50))
            painter.drawText(ox + 22, oy + 68, "★ Night Mode Active (<38)")
        else:
            painter.setPen(QColor(100, 230, 150))
            painter.drawText(ox + 22, oy + 68, "✓ Adequate Lighting")


class DiagnosticStudio(QtWidgets.QMainWindow):
    """Comprehensive Diagnostic & Verification Studio Window."""

    def __init__(self, target_user: str = "stealthtensor"):
        super().__init__()
        self.setWindowTitle("Glimpse • Biometric Diagnostic & Model Verification Studio")
        self.resize(1180, 780)

        self.target_user = target_user
        self.illuminator = ScreenIlluminator()

        # Dark theme styling
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d0f14;
                color: #e4e7eb;
            }
            QWidget {
                background-color: transparent;
                color: #e4e7eb;
                font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif;
            }
            QGroupBox {
                border: 1px solid #202634;
                border-radius: 8px;
                margin-top: 14px;
                padding-top: 16px;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: #6a788e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QProgressBar {
                border: 1px solid #1c2230;
                border-radius: 6px;
                background-color: #121620;
                text-align: center;
                height: 20px;
                font-weight: bold;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00aa66, stop:1 #00ff88);
                border-radius: 5px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #1e2536;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 1px solid #3b82f6;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QPushButton {
                background-color: #1e2638;
                border: 1px solid #2e3b55;
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: 600;
                font-size: 12px;
                color: #e4e7eb;
            }
            QPushButton:hover {
                background-color: #2b364e;
                border-color: #435478;
            }
            QPushButton:pressed {
                background-color: #161c2b;
            }
            QComboBox {
                background-color: #161c28;
                border: 1px solid #283348;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: 500;
                color: #f1f3f5;
            }
        """)

        # Main Layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QHBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(18)

        # ── Left: Video Pane ──
        video_container = QtWidgets.QVBoxLayout()
        self.video_widget = VideoWidget()
        video_container.addWidget(self.video_widget, stretch=1)

        # Video control buttons bar
        btn_bar = QtWidgets.QHBoxLayout()
        self.btn_illuminate = QtWidgets.QPushButton("☀ Test Screen Floodlight (Night Assist)")
        self.btn_illuminate.clicked.connect(self._toggle_illuminator)
        self.is_illuminating = False

        self.btn_snapshot = QtWidgets.QPushButton("📷 Save Diagnostic Snapshot")
        self.btn_snapshot.clicked.connect(self._save_snapshot)

        btn_bar.addWidget(self.btn_illuminate)
        btn_bar.addWidget(self.btn_snapshot)
        video_container.addLayout(btn_bar)

        main_layout.addLayout(video_container, stretch=6)

        # ── Right: Real-time Telemetry & Metrics Panel ──
        sidebar = QtWidgets.QVBoxLayout()
        sidebar.setSpacing(12)

        # Header Title
        title_box = QtWidgets.QVBoxLayout()
        title_lbl = QtWidgets.QLabel("Glimpse Biometric Studio")
        title_lbl.setFont(QFont("Inter, sans-serif", 17, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #ffffff;")
        sub_lbl = QtWidgets.QLabel("Real-time Inference, Cosine Similarity & Liveness Verification")
        sub_lbl.setStyleSheet("color: #7d8b9e; font-size: 12px;")
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)
        sidebar.addLayout(title_box)

        # 1. Primary Verdict Banner
        self.verdict_card = QtWidgets.QFrame()
        self.verdict_card.setStyleSheet("""
            QFrame {
                background-color: #131926;
                border: 2px solid #23304a;
                border-radius: 10px;
                padding: 12px;
            }
        """)
        verdict_layout = QtWidgets.QVBoxLayout(self.verdict_card)
        verdict_layout.setContentsMargins(10, 8, 10, 8)
        self.lbl_verdict_title = QtWidgets.QLabel("NO FACE DETECTED")
        self.lbl_verdict_title.setFont(QFont("Inter, sans-serif", 14, QFont.Weight.Bold))
        self.lbl_verdict_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_verdict_title.setStyleSheet("color: #8c9ba5;")

        self.lbl_verdict_sub = QtWidgets.QLabel("Position face inside camera frame")
        self.lbl_verdict_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_verdict_sub.setStyleSheet("color: #65758a; font-size: 11px;")

        verdict_layout.addWidget(self.lbl_verdict_title)
        verdict_layout.addWidget(self.lbl_verdict_sub)
        sidebar.addWidget(self.verdict_card)

        # 2. Biometric Vector Matching Box
        grp_match = QtWidgets.QGroupBox("Biometric Vector Matching")
        match_vbox = QtWidgets.QVBoxLayout(grp_match)

        # User Profile Selector
        user_row = QtWidgets.QHBoxLayout()
        user_lbl = QtWidgets.QLabel("Profile Target:")
        self.combo_user = QtWidgets.QComboBox()
        self.combo_user.addItems(["stealthtensor"])
        self.combo_user.currentTextChanged.connect(self._on_user_changed)
        user_row.addWidget(user_lbl)
        user_row.addWidget(self.combo_user, stretch=1)
        match_vbox.addLayout(user_row)

        # Similarity Score Row
        score_row = QtWidgets.QHBoxLayout()
        self.lbl_score_val = QtWidgets.QLabel("0.0000")
        self.lbl_score_val.setFont(QFont("JetBrains Mono, monospace", 24, QFont.Weight.Bold))
        self.lbl_score_val.setStyleSheet("color: #ffffff;")

        score_details = QtWidgets.QVBoxLayout()
        self.lbl_score_status = QtWidgets.QLabel("Cosine Similarity")
        self.lbl_score_status.setStyleSheet("color: #8fa0b5; font-size: 11px;")
        self.lbl_margin = QtWidgets.QLabel("Margin: +0.000")
        self.lbl_margin.setStyleSheet("color: #718296; font-size: 11px;")
        score_details.addWidget(self.lbl_score_status)
        score_details.addWidget(self.lbl_margin)

        score_row.addWidget(self.lbl_score_val)
        score_row.addLayout(score_details)
        match_vbox.addLayout(score_row)

        # Progress bar gauge
        self.bar_sim = QtWidgets.QProgressBar()
        self.bar_sim.setRange(0, 1000)
        self.bar_sim.setValue(0)
        self.bar_sim.setFormat("%v / 1000 (Similarity)")
        match_vbox.addWidget(self.bar_sim)

        # Interactive Threshold Slider
        thresh_header = QtWidgets.QHBoxLayout()
        self.lbl_thresh_label = QtWidgets.QLabel("Sensitivity Threshold:")
        self.lbl_thresh_label.setStyleSheet("color: #8fa0b5; font-size: 11px;")
        self.lbl_thresh_val = QtWidgets.QLabel("0.450 (Sudo Default)")
        self.lbl_thresh_val.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")
        thresh_header.addWidget(self.lbl_thresh_label)
        thresh_header.addStretch()
        thresh_header.addWidget(self.lbl_thresh_val)
        match_vbox.addLayout(thresh_header)

        self.slider_thresh = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.slider_thresh.setRange(200, 850) # 0.20 to 0.85
        self.slider_thresh.setValue(450)
        self.slider_thresh.valueChanged.connect(self._on_slider_changed)
        match_vbox.addWidget(self.slider_thresh)

        # Templates Info
        self.lbl_templates_info = QtWidgets.QLabel("Enrolled: 5 vectors | Match Vector: #--")
        self.lbl_templates_info.setStyleSheet("color: #7d8b9e; font-size: 11px;")
        match_vbox.addWidget(self.lbl_templates_info)

        sidebar.addWidget(grp_match)

        # 3. Liveness & Anti-Spoofing Box
        grp_live = QtWidgets.QGroupBox("RGB Liveness & Anti-Spoofing")
        live_vbox = QtWidgets.QVBoxLayout(grp_live)

        self.lbl_live_verdict = QtWidgets.QLabel("● Liveness: Evaluating...")
        self.lbl_live_verdict.setFont(QFont("Inter, sans-serif", 11, QFont.Weight.Bold))
        self.lbl_live_verdict.setStyleSheet("color: #facc15;")
        live_vbox.addWidget(self.lbl_live_verdict)

        self.lbl_motion_metric = QtWidgets.QLabel("Micro-Motion STD: 0.0000 (min 0.0005)")
        self.lbl_motion_metric.setStyleSheet("color: #8fa0b5; font-size: 11px;")
        live_vbox.addWidget(self.lbl_motion_metric)

        self.lbl_parallax_metric = QtWidgets.QLabel("3D Parallax STD: 0.0000 (min 0.0005)")
        self.lbl_parallax_metric.setStyleSheet("color: #8fa0b5; font-size: 11px;")
        live_vbox.addWidget(self.lbl_parallax_metric)

        self.lbl_texture_metric = QtWidgets.QLabel("Texture Clarity (Laplacian): 0.0 (min 15.0)")
        self.lbl_texture_metric.setStyleSheet("color: #8fa0b5; font-size: 11px;")
        live_vbox.addWidget(self.lbl_texture_metric)

        sidebar.addWidget(grp_live)

        # 4. Hardware & Pipeline Latency
        grp_perf = QtWidgets.QGroupBox("Pipeline Latency & Hardware")
        perf_vbox = QtWidgets.QVBoxLayout(grp_perf)

        self.lbl_perf_fps = QtWidgets.QLabel("Throughput: 0.0 FPS")
        self.lbl_perf_fps.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11px;")
        perf_vbox.addWidget(self.lbl_perf_fps)

        self.lbl_perf_breakdown = QtWidgets.QLabel("Detect: 0.0ms | SFace: 0.0ms | Match: 0.0ms")
        self.lbl_perf_breakdown.setStyleSheet("color: #8fa0b5; font-size: 11px;")
        perf_vbox.addWidget(self.lbl_perf_breakdown)

        self.lbl_perf_camera = QtWidgets.QLabel("Device: /dev/video0 (HP Wide Vision HD)")
        self.lbl_perf_camera.setStyleSheet("color: #718096; font-size: 11px;")
        perf_vbox.addWidget(self.lbl_perf_camera)

        sidebar.addWidget(grp_perf)
        sidebar.addStretch()

        main_layout.addLayout(sidebar, stretch=4)

        # Start Background AI Pipeline Worker
        self.worker = DiagnosticWorker(camera_idx=0, target_user=self.target_user)
        self.worker.frame_processed.connect(self._on_frame_processed)
        self.worker.start()

        self.last_frame: Optional[np.ndarray] = None
        self.last_metrics: Dict[str, Any] = {}

    def _on_frame_processed(self, frame: np.ndarray, metrics: dict):
        self.last_frame = frame
        self.last_metrics = metrics
        self.video_widget.update_frame(frame, metrics)

        # Update Verdict Banner
        has_face = metrics.get("has_face", False)
        is_match = metrics.get("is_match", False)
        sim = metrics.get("similarity", 0.0)
        target = metrics.get("target_user", "")
        thresh = metrics.get("threshold", 0.363)
        margin = metrics.get("margin", 0.0)

        if not has_face:
            self.lbl_verdict_title.setText("NO FACE DETECTED")
            self.lbl_verdict_title.setStyleSheet("color: #718096;")
            self.lbl_verdict_sub.setText("Position face inside camera view")
            self.verdict_card.setStyleSheet("QFrame { background-color: #131926; border: 2px solid #23304a; border-radius: 10px; padding: 12px; }")
        elif is_match:
            self.lbl_verdict_title.setText(f"✓ MATCH VERIFIED: {target}")
            self.lbl_verdict_title.setStyleSheet("color: #00f58c;")
            self.lbl_verdict_sub.setText(f"Similarity: {sim:.4f} exceeds threshold {thresh:.3f} (+{margin:.4f})")
            self.verdict_card.setStyleSheet("QFrame { background-color: #08291e; border: 2px solid #00f58c; border-radius: 10px; padding: 12px; }")
        else:
            self.lbl_verdict_title.setText("✕ UNENROLLED / STRANGER")
            self.lbl_verdict_title.setStyleSheet("color: #ff4155;")
            self.lbl_verdict_sub.setText(f"Similarity {sim:.4f} is BELOW threshold {thresh:.3f} ({margin:.4f})")
            self.verdict_card.setStyleSheet("QFrame { background-color: #2b1116; border: 2px solid #ff4155; border-radius: 10px; padding: 12px; }")

        # Similarity Score Display
        self.lbl_score_val.setText(f"{sim:.4f}")
        bar_val = int(min(1.0, max(0.0, sim)) * 1000)
        self.bar_sim.setValue(bar_val)

        if is_match:
            self.lbl_score_val.setStyleSheet("color: #00f58c;")
            self.bar_sim.setStyleSheet("QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00aa66, stop:1 #00ff88); }")
            self.lbl_margin.setText(f"Margin: +{margin:.4f} (SAFE ACCESS)")
            self.lbl_margin.setStyleSheet("color: #00f58c; font-weight: bold; font-size: 11px;")
        else:
            self.lbl_score_val.setStyleSheet("color: #ff4155;" if has_face else "color: #ffffff;")
            self.bar_sim.setStyleSheet("QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #cc2233, stop:1 #ff4155); }")
            self.lbl_margin.setText(f"Margin: {margin:.4f} (REJECTED)")
            self.lbl_margin.setStyleSheet("color: #ff4155; font-size: 11px;")

        top_idx = metrics.get("top_template_idx", -1)
        cnt = metrics.get("enrolled_count", 0)
        norm = metrics.get("candidate_norm", 0.0)
        t_str = f"#{top_idx + 1}" if top_idx >= 0 else "None"
        self.lbl_templates_info.setText(f"Enrolled: {cnt} templates | Best: Template {t_str} | Norm: {norm:.2f}")

        # Liveness Display
        is_live = metrics.get("liveness_is_live")
        cues = metrics.get("liveness_cues", {})
        m_std = cues.get("micro_motion_std", 0.0)
        p_std = cues.get("3d_parallax_std", 0.0)
        tex = cues.get("texture_variance", 0.0)

        if is_live is True:
            self.lbl_live_verdict.setText("● Liveness: LIVE HUMAN (Pass)")
            self.lbl_live_verdict.setStyleSheet("color: #00f58c; font-weight: bold;")
        elif is_live is False:
            self.lbl_live_verdict.setText("● Liveness: SPOOF REJECTED (Fail)")
            self.lbl_live_verdict.setStyleSheet("color: #ff4155; font-weight: bold;")
        else:
            self.lbl_live_verdict.setText("● Liveness: Accumulating frames...")
            self.lbl_live_verdict.setStyleSheet("color: #facc15; font-weight: bold;")

        self.lbl_motion_metric.setText(f"Micro-Motion STD: {m_std:.5f} {'✓' if m_std >= 0.0005 else '✗'}")
        self.lbl_parallax_metric.setText(f"3D Parallax STD: {p_std:.5f} {'✓' if p_std >= 0.0005 else '✗'}")
        self.lbl_texture_metric.setText(f"Texture Variance: {tex:.1f} {'✓' if tex >= 15.0 else '✗'}")

        # Performance Display
        fps = metrics.get("fps", 0.0)
        t_tot = metrics.get("timing_total_ms", 0.0)
        t_det = metrics.get("timing_det_ms", 0.0)
        t_emb = metrics.get("timing_emb_ms", 0.0)
        t_match = metrics.get("timing_match_ms", 0.0)

        self.lbl_perf_fps.setText(f"Throughput: {fps:.1f} FPS (Total: {t_tot:.1f}ms)")
        self.lbl_perf_breakdown.setText(f"Detect: {t_det:.1f}ms | SFace: {t_emb:.1f}ms | Match: {t_match:.2f}ms")

    def _on_user_changed(self, username: str):
        self.worker.set_target_user(username)

    def _on_slider_changed(self, val: int):
        thresh = val / 1000.0
        label_text = f"{thresh:.3f}"
        if abs(thresh - 0.450) < 0.005:
            label_text += " (Sudo Default)"
        elif abs(thresh - 0.480) < 0.005:
            label_text += " (SDDM Default)"
        self.lbl_thresh_val.setText(label_text)
        self.worker.set_threshold(thresh)

    def _toggle_illuminator(self):
        if not self.is_illuminating:
            self.is_illuminating = True
            self.btn_illuminate.setText("■ Extinguish Screen Floodlight")
            self.btn_illuminate.setStyleSheet("background-color: #f59e0b; color: #000000; font-weight: bold;")
            self.illuminator.illuminate()
        else:
            self.is_illuminating = False
            self.btn_illuminate.setText("☀ Test Screen Floodlight (Night Assist)")
            self.btn_illuminate.setStyleSheet("")
            self.illuminator.extinguish()

    def _save_snapshot(self):
        if self.last_frame is None:
            return

        ts = int(time.time())
        out_img = Path(f"/tmp/glimpse_diagnostic_{ts}.png")
        out_json = Path(f"/tmp/glimpse_diagnostic_{ts}.json")

        # Save annotated image
        annotated = self.last_frame.copy()
        if self.last_metrics.get("bbox"):
            x, y, w, h = self.last_metrics["bbox"]
            is_m = self.last_metrics.get("is_match", False)
            sim = self.last_metrics.get("similarity", 0.0)
            col = (0, 245, 140) if is_m else (65, 65, 255)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), col, 2)
            cv2.putText(annotated, f"Sim: {sim:.4f} ({'PASS' if is_m else 'FAIL'})", (x, max(20, y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)

        cv2.imwrite(str(out_img), annotated)
        with open(out_json, "w") as f:
            json.dump(self.last_metrics, f, indent=2)

        QtWidgets.QMessageBox.information(
            self,
            "Snapshot Saved",
            f"Diagnostic frame and metrics saved to:\n• {out_img}\n• {out_json}"
        )

    def closeEvent(self, event):
        self.illuminator.extinguish()
        self.worker.stop()
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    user = sys.argv[1] if len(sys.argv) > 1 else "stealthtensor"
    studio = DiagnosticStudio(target_user=user)
    studio.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
