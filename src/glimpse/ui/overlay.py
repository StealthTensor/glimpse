"""
Glimpse Apple FaceID Top-Attached Notch Overlay.
Exact Boring Notch / Apple MacBook contour attached flush to top screen bezel (y=0) with curved flares.
Square body dimensions (160x160), pure borderless OLED black, zero green dot, zero glyph bounce.
Fluid ease drop-down expansion (OutCubic) and slide-up retraction (OutCubic).
Includes Night Mode Screen Illuminator for pitch-black rooms (automatic screen edge fill & brightness boost).
Plays Apple 60 FPS video assets inside the notch.
"""

from __future__ import annotations
import os
import sys
import json
import time
import socket
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Ensure reliable absolute top-center placement on KDE Wayland via XWayland
if "QT_QPA_PLATFORM" not in os.environ and "WAYLAND_DISPLAY" in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QPixmap

from glimpse.ui.illuminator import ScreenIlluminator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [glimpse-ui] %(message)s")
logger = logging.getLogger("glimpse.ui")


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
FRAMES_SUCCESS_DIR = ASSETS_DIR / "frames_success"
FRAMES_FAILURE_DIR = ASSETS_DIR / "frames_failure"
STATIC_FRAME_PATH = ASSETS_DIR / "unlockstatic.png"
USER_CONFIG_PATH = Path.home() / ".config" / "glimpse" / "ui.json"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "ui.json"

CURVES: Dict[str, QtCore.QEasingCurve.Type] = {
    "OutCubic": QtCore.QEasingCurve.Type.OutCubic,
    "InCubic": QtCore.QEasingCurve.Type.InCubic,
    "InOutCubic": QtCore.QEasingCurve.Type.InOutCubic,
    "OutQuad": QtCore.QEasingCurve.Type.OutQuad,
    "InQuad": QtCore.QEasingCurve.Type.InQuad,
    "InOutQuad": QtCore.QEasingCurve.Type.InOutQuad,
    "OutExpo": QtCore.QEasingCurve.Type.OutExpo,
    "InExpo": QtCore.QEasingCurve.Type.InExpo,
    "OutSine": QtCore.QEasingCurve.Type.OutSine,
    "InSine": QtCore.QEasingCurve.Type.InSine,
    "Linear": QtCore.QEasingCurve.Type.Linear,
    "OutBack": QtCore.QEasingCurve.Type.OutBack,
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "style": "apple_top_notch",
    "dimensions": {
        "body_width": 160,
        "expanded_height": 160,
        "top_radius": 18,
        "bottom_radius": 40,
        "glyph_size": 110,
        "glyph_y_offset": -1
    },
    "timings": {
        "drop_duration_ms": 440,
        "retract_duration_ms": 340,
        "drop_curve": "OutCubic",
        "retract_curve": "OutCubic",
        "success_hold_ms": 1100,
        "failure_hold_ms": 1400
    }
}

def load_ui_config(custom_path: Optional[str] = None) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    target = None
    if custom_path and Path(custom_path).exists():
        target = Path(custom_path)
    elif USER_CONFIG_PATH.exists():
        target = USER_CONFIG_PATH
    elif DEFAULT_CONFIG_PATH.exists():
        target = DEFAULT_CONFIG_PATH

    if target:
        try:
            with open(target, "r") as f:
                user_data = json.load(f)
            for sec, vals in user_data.items():
                if isinstance(vals, dict) and sec in cfg:
                    cfg[sec].update(vals)
                else:
                    cfg[sec] = vals
        except Exception as e:
            logger.warning(f"Failed to parse config from {target}: {e}")
    return cfg


class EventWorker(QtCore.QThread):
    """Listens on glimpsed events socket and emits Qt signals."""
    scan_started = pyqtSignal(dict)
    auth_success = pyqtSignal(dict)
    auth_failure = pyqtSignal(dict)
    night_mode_on = pyqtSignal(dict)
    night_mode_off = pyqtSignal(dict)

    def __init__(self, socket_path: Optional[str] = None):
        super().__init__()
        if socket_path:
            self.socket_path = Path(socket_path)
        else:
            # Check system socket first (cold boot / root daemon), then user socket
            sys_sock = Path("/run/glimpse/events.sock")
            if sys_sock.exists() or os.geteuid() == 0:
                self.socket_path = sys_sock
            else:
                self.socket_path = Path.home() / ".local" / "share" / "glimpse" / "events.sock"
        self.running = True

    def run(self):
        while self.running:
            if not self.socket_path.exists():
                time.sleep(0.3)
                continue

            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(str(self.socket_path))
                sock.settimeout(1.0)
                buffer = ""

                while self.running:
                    try:
                        data = sock.recv(2048)
                        if not data:
                            break
                        buffer += data.decode("utf-8")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            if not line.strip():
                                continue
                            msg = json.loads(line)
                            ev = msg.get("event")
                            if ev == "scan_started":
                                self.scan_started.emit(msg)
                            elif ev == "auth_success":
                                self.auth_success.emit(msg)
                            elif ev == "auth_failure":
                                self.auth_failure.emit(msg)
                            elif ev == "night_mode_on":
                                self.night_mode_on.emit(msg)
                            elif ev == "night_mode_off":
                                self.night_mode_off.emit(msg)
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                sock.close()
            except Exception:
                time.sleep(0.5)

    def stop(self):
        self.running = False


class AppleFaceIDTopNotchOverlay(QtWidgets.QWidget):
    """
    Apple FaceID Notch attached flush to top screen bezel (y=0).
    Curved top flares seamlessly anchor the notch into the top bezel.
    Square body (160x160), pure borderless OLED black, zero green dot, zero glyph bounce.
    Plays Apple 60 FPS video assets inside the notch.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.cfg = config or load_ui_config()

        # Frameless, transparent, always on top, bypass WM decorations
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Pre-load 60 FPS Apple FaceID video animation frames
        self.frames_success: List[QPixmap] = []
        self.frames_failure: List[QPixmap] = []
        self._load_frames()

        self.pixmap_static = QPixmap(str(STATIC_FRAME_PATH)) if STATIC_FRAME_PATH.exists() else None

        # Screen Illuminator (Night Mode)
        self.illuminator = ScreenIlluminator(config=self.cfg)


        # Dimensions & Geometry
        dims = self.cfg.get("dimensions", DEFAULT_CONFIG["dimensions"])
        self.body_w = float(dims.get("body_width", 160))
        self.notch_max_h = float(dims.get("expanded_height", 160))
        self.top_r = float(dims.get("top_radius", 18))
        self.bot_r = float(dims.get("bottom_radius", 40))
        self.glyph_size = float(dims.get("glyph_size", 110))
        self.glyph_y_offset = float(dims.get("glyph_y_offset", -1))

        # Total width including top curved flares
        self.total_w = self.body_w + 2.0 * self.top_r
        self.canvas_w = int(self.total_w + 48)
        self.canvas_h = int(self.notch_max_h + 30)

        # State machine
        self.state = "idle" # idle, scanning, success, failure, collapsing
        self.current_h = 0.0
        self.shake_offset = 0.0

        # 60 FPS playback timer for Apple FaceID frames
        self.frame_idx = 0
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(16)
        self.playback_timer.timeout.connect(self._advance_frame)

        # Animation timings & curves
        timings = self.cfg.get("timings", DEFAULT_CONFIG["timings"])
        drop_dur = int(timings.get("drop_duration_ms", 440))
        retract_dur = int(timings.get("retract_duration_ms", 340))
        drop_curve_name = timings.get("drop_curve", "OutCubic")
        retract_curve_name = timings.get("retract_curve", "OutCubic")
        drop_curve = CURVES.get(drop_curve_name, QtCore.QEasingCurve.Type.OutCubic)
        retract_curve = CURVES.get(retract_curve_name, QtCore.QEasingCurve.Type.OutCubic)

        # Fluid Drop-Down Expansion Animation
        self.expand_anim = QtCore.QVariantAnimation(self)
        self.expand_anim.setDuration(drop_dur)
        self.expand_anim.setStartValue(float(0.0))
        self.expand_anim.setEndValue(float(self.notch_max_h))
        self.expand_anim.setEasingCurve(drop_curve)
        self.expand_anim.valueChanged.connect(self._on_anim_step)

        # Fluid Retract-Up Retraction Animation
        self.collapse_anim = QtCore.QVariantAnimation(self)
        self.collapse_anim.setDuration(retract_dur)
        self.collapse_anim.setStartValue(float(self.notch_max_h))
        self.collapse_anim.setEndValue(float(0.0))
        self.collapse_anim.setEasingCurve(retract_curve)
        self.collapse_anim.valueChanged.connect(self._on_anim_step)
        self.collapse_anim.finished.connect(self._on_collapse_finished)

        self._update_geometry()

    def _load_frames(self):
        if FRAMES_SUCCESS_DIR.exists():
            files = sorted(FRAMES_SUCCESS_DIR.glob("*.png"))
            for f in files:
                self.frames_success.append(QPixmap(str(f)))
        if FRAMES_FAILURE_DIR.exists():
            files = sorted(FRAMES_FAILURE_DIR.glob("*.png"))
            for f in files:
                self.frames_failure.append(QPixmap(str(f)))

    def _update_geometry(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen:
            geom = screen.geometry()
            x = geom.x() + (geom.width() - self.canvas_w) // 2
            y = geom.y() # Flush against top bezel (y = 0)
            self.setGeometry(x, y, self.canvas_w, self.canvas_h)

    # ── State Triggers ──

    def start_scan(self):
        """Expand square notch smoothly downwards from top bezel."""
        self.state = "scanning"
        self.shake_offset = 0.0
        self.frame_idx = 0

        self._update_geometry()
        self.show()
        self.raise_()

        self.collapse_anim.stop()
        self.expand_anim.stop()
        self.expand_anim.setStartValue(float(self.current_h))
        self.expand_anim.setEndValue(float(self.notch_max_h))
        self.expand_anim.start()

    def trigger_success(self, duration_ms: float = 0.0):
        """Play Apple unlock checkmark video at 60 FPS (no bounce, steady position)."""
        self.state = "success"

        # Extinguish night mode fill light if active
        self.illuminator.extinguish()

        # Play 60 FPS animation sequence (73 frames of unlockanimation.mp4)
        self.frame_idx = 0
        self.playback_timer.start()

        hold_time = self.cfg.get("timings", {}).get("success_hold_ms", 1100)
        QTimer.singleShot(hold_time, self.collapse)

    def trigger_failure(self, reason: str = ""):
        """Play failure video at 60 FPS and shake horizontally."""
        self.state = "failure"

        # Extinguish night mode fill light if active
        self.illuminator.extinguish()

        self.frame_idx = 0
        self.playback_timer.start()

        self._shake_step(0)

        hold_time = self.cfg.get("timings", {}).get("failure_hold_ms", 1400)
        QTimer.singleShot(hold_time, self.collapse)

    def collapse(self):
        """Retract notch smoothly back up into top bezel."""
        self.state = "collapsing"
        self.illuminator.extinguish()
        self.playback_timer.stop()
        self.expand_anim.stop()
        self.collapse_anim.stop()
        self.collapse_anim.setStartValue(float(self.current_h))
        self.collapse_anim.setEndValue(float(0.0))
        self.collapse_anim.start()

    def _on_anim_step(self, val: float):
        self.current_h = float(val)
        self.update()

    def _on_collapse_finished(self):
        self.state = "idle"
        self.illuminator.extinguish()
        self.hide()

    def _advance_frame(self):
        if self.state == "success":
            if self.frame_idx < len(self.frames_success) - 1:
                self.frame_idx += 1
                self.update()
            else:
                self.playback_timer.stop() # Hold final resolved checkmark frame
        elif self.state == "failure":
            if self.frame_idx < len(self.frames_failure) - 1:
                self.frame_idx += 1
                self.update()
            else:
                self.playback_timer.stop()

    def _shake_step(self, step: int):
        shakes = [0, -10, 10, -7, 7, -4, 4, -1, 1, 0]
        if step < len(shakes) and self.state == "failure":
            self.shake_offset = float(shakes[step])
            self.update()
            QTimer.singleShot(28, lambda: self._shake_step(step + 1))
        else:
            self.shake_offset = 0.0
            self.update()

    # ── Path Construction: Curved Notch Attached to Top Screen Bezel ──

    def _build_notch_path(self, x: float, y: float, total_w: float, h: float, top_r: float, bot_r: float) -> QPainterPath:
        """
        Builds the Apple MacBook / Boring Notch contour attached flush to top bezel (y=0).
        Concave outward flares attach smoothly into the bezel.
        Smooth rounded corners at the bottom.
        """
        path = QPainterPath()
        # 1. Start at top-left bezel attachment
        path.moveTo(x, y)
        # 2. Top-left concave outward flare into notch body
        path.quadTo(x + top_r, y, x + top_r, y + top_r)
        # 3. Down left edge of body
        path.lineTo(x + top_r, y + h - bot_r)
        # 4. Bottom-left rounded corner
        path.quadTo(x + top_r, y + h, x + top_r + bot_r, y + h)
        # 5. Across bottom edge
        path.lineTo(x + total_w - top_r - bot_r, y + h)
        # 6. Bottom-right rounded corner
        path.quadTo(x + total_w - top_r, y + h, x + total_w - top_r, y + h - bot_r)
        # 7. Up right edge of body
        path.lineTo(x + total_w - top_r, y + top_r)
        # 8. Top-right concave outward flare attaching to top bezel
        path.quadTo(x + total_w - top_r, y, x + total_w, y)
        # 9. Close along top bezel line
        path.lineTo(x, y)
        path.closeSubpath()
        return path

    # ── Paint Event: Top-Attached Borderless OLED Black Notch ──

    def paintEvent(self, event):
        # Ignore sub-pixel artifacts at the very end of collapse
        if self.state == "idle" or self.current_h <= 2.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        cx = self.width() / 2.0 + self.shake_offset
        y = 0.0
        h = self.current_h

        # 1. Smooth dynamic width morphing near top bezel (prevents flat, wide rectangular strip)
        if h < 55.0:
            w_factor = (h / 55.0) ** 0.55
            current_body_w = self.body_w * w_factor
        else:
            current_body_w = self.body_w

        # 2. Curvature preservation: bottom corners stay round as physically possible at all heights
        bot_r = min(self.bot_r, h * 0.46, (current_body_w / 2.0) * 0.9)
        top_r = min(self.top_r, h * 0.30, (current_body_w / 2.0) * 0.5)
        current_total_w = current_body_w + 2.0 * top_r

        x = cx - current_total_w / 2.0

        notch_path = self._build_notch_path(x, y, current_total_w, h, top_r, bot_r)

        # 3. Soft opacity fade in the final 16px to dissolve seamlessly into top bezel
        notch_opacity = min(1.0, max(0.0, (h - 2.0) / 16.0)) if h < 18.0 else 1.0
        painter.setOpacity(notch_opacity)

        # Ambient soft shadow
        shadow_path = self._build_notch_path(x - 2.0, y, current_total_w + 4.0, h + 3.0, top_r + 1.0, bot_r + 2.0)
        painter.fillPath(shadow_path, QBrush(QColor(0, 0, 0, 110)))

        # Pure Deep OLED Jet-Black Body (#000000)
        painter.fillPath(notch_path, QBrush(QColor(0, 0, 0, 255)))

        # ZERO BORDER - Completely Borderless
        painter.setPen(Qt.PenStyle.NoPen)

        # ── Center Apple FaceID Animation Asset (No bounce, steady scale 1.0) ──
        if self.current_h < 60.0:
            return

        glyph_opacity = notch_opacity * min(1.0, (self.current_h - 60.0) / 50.0)
        glyph_size = self.glyph_size

        # Configured vertical position via glyph_y_offset
        glyph_cy = (self.current_h * 0.5) + self.glyph_y_offset
        glyph_rect = QRectF(
            cx - glyph_size / 2.0,
            glyph_cy - glyph_size / 2.0,
            glyph_size,
            glyph_size
        )

        pix: Optional[QPixmap] = None
        if self.state == "success" and self.frames_success:
            pix = self.frames_success[min(self.frame_idx, len(self.frames_success) - 1)]
        elif self.state == "failure" and self.frames_failure:
            pix = self.frames_failure[min(self.frame_idx, len(self.frames_failure) - 1)]
        else:
            pix = self.pixmap_static

        if pix and not pix.isNull():
            painter.setOpacity(glyph_opacity)
            painter.drawPixmap(glyph_rect.toRect(), pix)
            painter.setOpacity(1.0)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Glimpse Apple FaceID Top-Attached Notch UI")
    parser.add_argument("--demo", action="store_true", help="Run standalone demonstration sequence")
    parser.add_argument("--night", action="store_true", help="Demonstrate night mode fill flash in demo")
    parser.add_argument("--config", type=str, default=None, help="Path to custom JSON config")
    parser.add_argument("--width", type=int, default=None, help="Body width (default: 160)")
    parser.add_argument("--height", type=int, default=None, help="Expanded drop height (default: 160)")
    parser.add_argument("--top-radius", type=int, default=None, help="Top bezel flare radius (default: 18)")
    parser.add_argument("--bot-radius", type=int, default=None, help="Bottom corner radius (default: 40)")
    parser.add_argument("--glyph-size", type=int, default=None, help="FaceID video size (default: 110)")
    parser.add_argument("--glyph-y-offset", type=float, default=None, help="Vertical offset for face (default: -1)")
    parser.add_argument("--drop-ms", type=int, default=None, help="Drop duration in ms (default: 440)")
    parser.add_argument("--retract-ms", type=int, default=None, help="Retract duration in ms (default: 340)")
    parser.add_argument("--drop-curve", type=str, default=None, help="Easing curve: OutCubic, OutQuad, OutExpo, etc.")
    parser.add_argument("--retract-curve", type=str, default=None, help="Easing curve: OutCubic, InCubic, InQuad, etc.")
    parser.add_argument("--ill-mode", type=str, default=None, help="Illumination mode: retina_flash or edge_glow")
    parser.add_argument("--ill-opacity", type=float, default=None, help="Illumination fill opacity (0.0 - 1.0)")
    parser.add_argument("--ill-brightness", type=int, default=None, help="Hardware screen brightness (1000 - 10000)")
    parser.add_argument("--glow-depth", type=float, default=None, help="Glow border depth in px for edge_glow mode")
    parser.add_argument("--socket", type=str, default=None, help="Path to events.sock")
    args = parser.parse_args()


    cfg = load_ui_config(args.config)
    dims = cfg.setdefault("dimensions", {})
    if args.width is not None:
        dims["body_width"] = args.width
    if args.height is not None:
        dims["expanded_height"] = args.height
    if args.top_radius is not None:
        dims["top_radius"] = args.top_radius
    if args.bot_radius is not None:
        dims["bottom_radius"] = args.bot_radius
    if args.glyph_size is not None:
        dims["glyph_size"] = args.glyph_size
    if args.glyph_y_offset is not None:
        dims["glyph_y_offset"] = args.glyph_y_offset

    timings = cfg.setdefault("timings", {})
    if args.drop_ms is not None:
        timings["drop_duration_ms"] = args.drop_ms
    if args.retract_ms is not None:
        timings["retract_duration_ms"] = args.retract_ms
    if args.drop_curve is not None:
        timings["drop_curve"] = args.drop_curve
    if args.retract_curve is not None:
        timings["retract_curve"] = args.retract_curve

    ill = cfg.setdefault("illumination", {})
    if args.ill_mode is not None:
        ill["mode"] = args.ill_mode
    if args.ill_opacity is not None:
        ill["fill_opacity"] = args.ill_opacity
    if args.ill_brightness is not None:
        ill["brightness"] = args.ill_brightness
    if args.glow_depth is not None:
        ill["glow_depth"] = args.glow_depth

    app = QtWidgets.QApplication(sys.argv)
    overlay = AppleFaceIDTopNotchOverlay(config=cfg)


    if args.demo:
        bw = dims.get("body_width", 160)
        eh = dims.get("expanded_height", 160)
        tr = dims.get("top_radius", 18)
        br = dims.get("bottom_radius", 40)
        g = dims.get("glyph_size", 110)
        gy = dims.get("glyph_y_offset", -1)
        d_ms = timings.get("drop_duration_ms", 440)
        r_ms = timings.get("retract_duration_ms", 340)
        dc = timings.get("drop_curve", "OutCubic")
        rc = timings.get("retract_curve", "OutCubic")
        print(f"[*] Running Apple FaceID Top-Attached Notch demonstration...")
        print(f"    • Anchor: Screen top bezel (y=0) with curved outward flares (r={tr}px)")
        print(f"    • Square Body: {bw}px wide × {eh}px drop (Bottom radius: {br}px)")
        print(f"    • Center Asset: {g}px (offset: {gy}px)")
        print(f"    • Motion: Drop={d_ms}ms ({dc}) | Retract={r_ms}ms ({rc})")
        print("    • Border: NONE (pure borderless OLED black)")
        print("    • Green LED: REMOVED")
        print("    • Bouncing: DISABLED (steady fluid video playback)")

        if args.night:
            m = overlay.illuminator.mode
            op = overlay.illuminator.fill_opacity
            br = overlay.illuminator.target_brightness
            print(f"    • Night Mode Illuminator: ENABLED (mode='{m}', opacity={op*100:.0f}%, brightness={br}/10000)")
            overlay.illuminator.illuminate()


        # Step 1: Fluid drop down
        QTimer.singleShot(200, lambda: overlay.start_scan())
        # Step 2: Trigger success
        QTimer.singleShot(2400, lambda: overlay.trigger_success())
        # Step 3: Exit after demo
        QTimer.singleShot(4200, lambda: app.quit())
    else:
        worker = EventWorker(socket_path=args.socket)
        worker.scan_started.connect(lambda msg: overlay.start_scan())
        worker.auth_success.connect(lambda msg: overlay.trigger_success(msg.get("duration_ms", 0)))
        worker.auth_failure.connect(lambda msg: overlay.trigger_failure(msg.get("reason", "")))
        worker.night_mode_on.connect(lambda msg: overlay.illuminator.illuminate())
        worker.night_mode_off.connect(lambda msg: overlay.illuminator.extinguish())
        worker.start()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
