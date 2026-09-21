"""
Glimpse Policy Engine.
Evaluates security policies per service and enforces strict access rules.
"""

from __future__ import annotations
import os
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("glimpse.policy")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_POLICY_PATH = PROJECT_ROOT / "config" / "policy.yaml"
USER_POLICY_PATH = Path.home() / ".config" / "glimpse" / "policy.yaml"
SYSTEM_POLICY_PATH = Path("/etc/glimpse/policy.yaml")

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "1.0",
    "default_policy": {
        "methods": ["face", "password"],
        "liveness_required": True,
        "min_similarity": 0.363,
        "max_timeout_sec": 2.5,
        "allow_password_fallback": True,
    },
    "services": {
        "sudo": {
            "methods": ["face", "password"],
            "liveness_required": True,
            "min_similarity": 0.363,
            "max_timeout_sec": 2.5,
            "allow_password_fallback": True,
        },
        "kde": {
            "methods": ["face", "password"],
            "liveness_required": True,
            "min_similarity": 0.363,
            "max_timeout_sec": 3.0,
            "allow_password_fallback": True,
        },
        "kscreenlocker": {
            "methods": ["face", "password"],
            "liveness_required": True,
            "min_similarity": 0.363,
            "max_timeout_sec": 3.0,
            "allow_password_fallback": True,
        },
        "sddm": {
            "methods": ["face", "password"],
            "liveness_required": True,
            "min_similarity": 0.380,
            "max_timeout_sec": 3.5,
            "allow_password_fallback": True,
        },
        "su": {
            "methods": ["password"],  # Root shell hopping: password strictly required
            "liveness_required": False,
            "min_similarity": 1.0,
            "max_timeout_sec": 0.0,
            "allow_password_fallback": True,
        },
        "app_protection": {
            "methods": ["face", "password"],
            "liveness_required": True,
            "min_similarity": 0.363,
            "max_timeout_sec": 3.0,
            "allow_password_fallback": True,
        },
        "folder_protection": {
            "methods": ["face", "password"],
            "liveness_required": True,
            "min_similarity": 0.363,
            "max_timeout_sec": 3.0,
            "allow_password_fallback": True,
        },
    },
}

@dataclass
class ServicePolicy:
    service_name: str
    methods: List[str]
    liveness_required: bool
    min_similarity: float
    max_timeout_sec: float
    allow_password_fallback: bool

    @property
    def is_face_allowed(self) -> bool:
        return "face" in self.methods

    @property
    def is_password_allowed(self) -> bool:
        return "password" in self.methods


class PolicyEngine:
    """Evaluates security rules for incoming authentication requests."""

    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)

    def _load_config(self, custom_path: Optional[str] = None) -> Dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        target = None

        if custom_path and Path(custom_path).exists():
            target = Path(custom_path)
        elif SYSTEM_POLICY_PATH.exists() and os.geteuid() == 0:
            target = SYSTEM_POLICY_PATH
        elif USER_POLICY_PATH.exists():
            target = USER_POLICY_PATH
        elif DEFAULT_POLICY_PATH.exists():
            target = DEFAULT_POLICY_PATH

        if target:
            try:
                with open(target, "r") as f:
                    loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    if "default_policy" in loaded:
                        cfg["default_policy"].update(loaded["default_policy"])
                    if "services" in loaded:
                        cfg["services"].update(loaded["services"])
                logger.info(f"Loaded security policy from {target}")
            except Exception as e:
                logger.warning(f"Failed to load policy from {target}: {e}")

        return cfg

    def evaluate(self, service: str, username: str = "") -> ServicePolicy:
        """Evaluate policy for a service (e.g. sudo, sddm, su, etc.)."""
        services = self.config.get("services", {})
        default = self.config.get("default_policy", DEFAULT_CONFIG["default_policy"])

        # Match exact service or sanitize prefix (e.g. sudo-i -> sudo)
        norm_service = service.lower().split("-")[0] if "-" in service else service.lower()

        sec = services.get(service, services.get(norm_service, default))

        return ServicePolicy(
            service_name=service,
            methods=list(sec.get("methods", default.get("methods", ["face", "password"]))),
            liveness_required=bool(sec.get("liveness_required", default.get("liveness_required", True))),
            min_similarity=float(sec.get("min_similarity", default.get("min_similarity", 0.363))),
            max_timeout_sec=float(sec.get("max_timeout_sec", default.get("max_timeout_sec", 2.5))),
            allow_password_fallback=bool(sec.get("allow_password_fallback", default.get("allow_password_fallback", True))),
        )
