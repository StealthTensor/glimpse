"""
Glimpse Screen Illuminator (Night Mode / Low-Light Assist).
Provides high-output photographic screen fill lighting and hardware brightness boost in dark rooms.
Features fluid fade-in and fade-out animations (OutCubic / OutQuad) for soft cinematic transitions.
Supports two modes:
  - "retina_flash": Fullscreen warm softbox floodlight (maximum face illumination, Apple style).
  - "edge_glow": Wide soft photographic perimeter halo with configurable depth.
"""

from __future__ import annotations
import os
import subprocess
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QBrush

from glimpse.daemon.backlight import BacklightManager

logger = logging.getLogger("glimpse.ui.illuminator")


class BrightnessManager:
    """Controls display hardware brightness with sysfs direct access and D-Bus fallback."""

    @staticmethod
    def get_brightness() -> Optional[int]:
        devs = BacklightManager._find_backlight_devices()
        for dev in devs:
            try:
                cur = int((dev / "brightness").read_text().strip())
                max_val = int((dev / "max_brightness").read_text().strip())
                return int((cur / max_val) * 10000)
            except Exception:
                pass
        return BacklightManager._get_dbus_brightness()

    @staticmethod
    def set_brightness(val: int) -> bool:
        devs = BacklightManager._find_backlight_devices()
        set_any = False
        for dev in devs:
            try:
                max_val = int((dev / "max_brightness").read_text().strip())
                target_val = int((val / 10000.0) * max_val)
                (dev / "brightness").write_text(str(target_val))
                set_any = True
            except Exception:
                pass
        if set_any:
            return True
        return BacklightManager._set_dbus_brightness(val)


class ScreenIlluminator(QtWidgets.QWidget):
    """
    High-output ambient screen fill lighting window with fluid fade-in and fade-out animations.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        cfg = config or {}
        ill_cfg = cfg.get("illumination", {})

        # Configuration parameters
        self.mode = ill_cfg.get("mode", "retina_flash") # "retina_flash" or "edge_glow"
        self.fill_opacity = float(ill_cfg.get("fill_opacity", 0.88)) # 0.0 - 1.0
        self.glow_depth = float(ill_cfg.get("glow_depth", 380.0)) # depth for edge_glow
        self.target_brightness = int(ill_cfg.get("brightness", 10000)) # max 10000 (100%)
        self.fade_in_ms = int(ill_cfg.get("fade_in_ms", 280)) # smooth ramp up
        self.fade_out_ms = int(ill_cfg.get("fade_out_ms", 320)) # smooth ramp down

        self.current_opacity = 0.0
        self.saved_brightness: Optional[int] = None
        self.is_illuminating = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Smooth Opacity Transition Animation
        self.fade_anim = QtCore.QVariantAnimation(self)
        self.fade_anim.valueChanged.connect(self._on_fade_step)
        self.fade_anim.finished.connect(self._on_fade_finished)

        self._update_geometry()

    def update_config(self, ill_cfg: Dict[str, Any]):
        """Dynamically update illumination parameters."""
        if "mode" in ill_cfg:
            self.mode = str(ill_cfg["mode"])
        if "fill_opacity" in ill_cfg:
            self.fill_opacity = float(ill_cfg["fill_opacity"])
        if "glow_depth" in ill_cfg:
            self.glow_depth = float(ill_cfg["glow_depth"])
        if "brightness" in ill_cfg:
            self.target_brightness = int(ill_cfg["brightness"])
        if "fade_in_ms" in ill_cfg:
            self.fade_in_ms = int(ill_cfg["fade_in_ms"])
        if "fade_out_ms" in ill_cfg:
            self.fade_out_ms = int(ill_cfg["fade_out_ms"])

    def _update_geometry(self):
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen:
            geom = screen.geometry()
            self.setGeometry(geom)

    def illuminate(self):
        """Turn on screen fill lighting with a smooth fade-in animation and brightness boost."""
        self.is_illuminating = True
        self._update_geometry()

        # 1. Save and boost brightness to target (100%)
        current = BrightnessManager.get_brightness()
        if current is not None and current < self.target_brightness:
            if self.saved_brightness is None:
                self.saved_brightness = current
            BrightnessManager.set_brightness(self.target_brightness)
            logger.info(f"Night mode: boosted brightness from {current} to {self.target_brightness}")

        # 2. Show window and start smooth fade-in animation
        self.show()
        self.update()

        self.fade_anim.stop()
        self.fade_anim.setDuration(self.fade_in_ms)
        self.fade_anim.setStartValue(float(self.current_opacity))
        self.fade_anim.setEndValue(float(self.fill_opacity))
        self.fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.fade_anim.start()

    def extinguish(self):
        """Smoothly fade out the screen fill light and restore original brightness."""
        if not self.is_illuminating and self.current_opacity <= 0.001:
            return

        self.is_illuminating = False

        # Start smooth fade-out animation
        self.fade_anim.stop()
        self.fade_anim.setDuration(self.fade_out_ms)
        self.fade_anim.setStartValue(float(self.current_opacity))
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
        self.fade_anim.start()

    def _on_fade_step(self, val: float):
        self.current_opacity = float(val)
        self.update()

    def _on_fade_finished(self):
        if not self.is_illuminating and self.current_opacity <= 0.001:
            self.hide()
            # Restore original brightness
            if self.saved_brightness is not None:
                BrightnessManager.set_brightness(self.saved_brightness)
                logger.info(f"Restored original brightness to {self.saved_brightness}")
                self.saved_brightness = None

    def paintEvent(self, event):
        if self.current_opacity <= 0.001:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())

        # Soft warm TrueTone fill color (255, 253, 248)
        alpha = int(max(0.0, min(1.0, self.current_opacity)) * 255)

        if self.mode == "retina_flash":
            # Mode A: Fullscreen Softbox Floodlight (maximum lumens for dark rooms)
            fill_color = QColor(255, 253, 248, alpha)
            painter.fillRect(QRectF(0, 0, w, h), QBrush(fill_color))

        else:
            # Mode B: Deep Edge Halo Glow (perimeter fill)
            d = min(self.glow_depth, w / 2.0, h / 2.0)
            c_outer = QColor(255, 252, 245, alpha)
            c_inner = QColor(255, 252, 245, 0)

            # 1. Top glow
            g_top = QLinearGradient(0, 0, 0, d)
            g_top.setColorAt(0.0, c_outer)
            g_top.setColorAt(1.0, c_inner)
            painter.fillRect(QRectF(0, 0, w, d), QBrush(g_top))

            # 2. Bottom glow
            g_bot = QLinearGradient(0, h, 0, h - d)
            g_bot.setColorAt(0.0, c_outer)
            g_bot.setColorAt(1.0, c_inner)
            painter.fillRect(QRectF(0, h - d, w, d), QBrush(g_bot))

            # 3. Left glow
            g_left = QLinearGradient(0, 0, d, 0)
            g_left.setColorAt(0.0, c_outer)
            g_left.setColorAt(1.0, c_inner)
            painter.fillRect(QRectF(0, 0, d, h), QBrush(g_left))

            # 4. Right glow
            g_right = QLinearGradient(w, 0, w - d, 0)
            g_right.setColorAt(0.0, c_outer)
            g_right.setColorAt(1.0, c_inner)
            painter.fillRect(QRectF(w - d, 0, d, h), QBrush(g_right))
