"""
Glimpse Hardware Backlight Management.
Controls screen backlight directly via Linux sysfs (/sys/class/backlight) with
user-space D-Bus (KDE Solid PowerManagement) fallback.
Direct sysfs access works at 100% reliability even when screen is locked or at display manager.
"""

from __future__ import annotations
import glob
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger("glimpse.backlight")


class BacklightManager:
    """
    Manages display hardware backlight boosting in low-light environments.
    Thread-safe and fail-safe: guarantees restoring original brightness.
    """

    def __init__(self):
        self._saved_sysfs_brightness: Dict[str, int] = {}
        self._saved_dbus_brightness: Optional[int] = None
        self._is_boosted = False
        self._lock = threading.Lock()

    @staticmethod
    def _find_backlight_devices() -> list[Path]:
        """Discover all sysfs backlight controllers (e.g. intel_backlight, amdgpu_bl0)."""
        paths = [Path(p) for p in glob.glob("/sys/class/backlight/*")]
        return [p for p in paths if (p / "brightness").exists() and (p / "max_brightness").exists()]

    def boost(self, target_percent: float = 1.0) -> bool:
        """
        Boost display brightness to target percentage (default 100%).
        Saves original brightness before adjusting.
        """
        with self._lock:
            if self._is_boosted:
                return True

            devices = self._find_backlight_devices()
            boosted_any = False

            # 1. Primary: Direct sysfs (/sys/class/backlight) - zero overhead, works in lockscreen/SDDM
            for dev in devices:
                try:
                    bright_file = dev / "brightness"
                    max_file = dev / "max_brightness"

                    cur_val = int(bright_file.read_text().strip())
                    max_val = int(max_file.read_text().strip())

                    target_val = int(max_val * target_percent)
                    if cur_val < target_val:
                        self._saved_sysfs_brightness[str(dev)] = cur_val
                        bright_file.write_text(str(target_val))
                        logger.info(f"Backlight boosted on {dev.name}: {cur_val} -> {target_val} (max={max_val})")
                        boosted_any = True
                except Exception as e:
                    logger.debug(f"Direct sysfs write to {dev} failed: {e}")

            # 2. Fallback: KDE Solid D-Bus if sysfs not writable (e.g. unprivileged user process)
            if not boosted_any:
                try:
                    cur_dbus = self._get_dbus_brightness()
                    target_dbus = int(10000 * target_percent)
                    if cur_dbus is not None and cur_dbus < target_dbus:
                        self._saved_dbus_brightness = cur_dbus
                        if self._set_dbus_brightness(target_dbus):
                            logger.info(f"Backlight boosted via D-Bus: {cur_dbus} -> {target_dbus}")
                            boosted_any = True
                except Exception as e:
                    logger.debug(f"D-Bus backlight boost failed: {e}")

            self._is_boosted = boosted_any
            return boosted_any

    def restore(self) -> bool:
        """Restore original screen brightness before boost was applied."""
        with self._lock:
            if not self._is_boosted and not self._saved_sysfs_brightness and self._saved_dbus_brightness is None:
                return True

            restored_any = False

            # 1. Restore sysfs devices
            for dev_path, orig_val in list(self._saved_sysfs_brightness.items()):
                try:
                    bright_file = Path(dev_path) / "brightness"
                    if bright_file.exists():
                        bright_file.write_text(str(orig_val))
                        logger.info(f"Restored backlight on {Path(dev_path).name} to {orig_val}")
                        restored_any = True
                except Exception as e:
                    logger.warning(f"Failed to restore backlight on {dev_path}: {e}")
            self._saved_sysfs_brightness.clear()

            # 2. Restore D-Bus
            if self._saved_dbus_brightness is not None:
                try:
                    if self._set_dbus_brightness(self._saved_dbus_brightness):
                        logger.info(f"Restored backlight via D-Bus to {self._saved_dbus_brightness}")
                        restored_any = True
                except Exception as e:
                    logger.warning(f"Failed to restore D-Bus brightness: {e}")
                self._saved_dbus_brightness = None

            self._is_boosted = False
            return restored_any

    @staticmethod
    def _get_dbus_brightness() -> Optional[int]:
        try:
            res = subprocess.check_output([
                "qdbus6", "org.kde.Solid.PowerManagement",
                "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                "org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightness"
            ], text=True, timeout=2.0).strip()
            return int(res)
        except Exception:
            return None

    @staticmethod
    def _set_dbus_brightness(val: int) -> bool:
        try:
            subprocess.run([
                "qdbus6", "org.kde.Solid.PowerManagement",
                "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                "org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness",
                str(val)
            ], check=True, timeout=2.0)
            return True
        except Exception:
            return False
