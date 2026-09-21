"""
Glimpse App & Folder Protection Subsystem.
Enforces FaceID authentication before launching protected applications or accessing sensitive folders.
"""

from __future__ import annotations
import os
import sys
import json
import stat
import shutil
import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("glimpse.protect")

CONFIG_DIR = Path.home() / ".local" / "share" / "glimpse"
PROTECTED_FOLDERS_FILE = CONFIG_DIR / "protected_folders.json"
LOCAL_BIN_DIR = Path.home() / ".local" / "bin"


import socket
import getpass

def verify_face_auth(timeout: float = 3.0, service: str = "folder_protection") -> bool:
    """Invokes FaceID authentication via glimpsed socket (triggering desktop notch) with CLI fallback."""
    username = getpass.getuser()
    for sock_path in ["/run/glimpse/glimpse.sock", str(CONFIG_DIR / "glimpse.sock")]:
        if os.path.exists(sock_path):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(timeout + 2.0)
                s.connect(sock_path)
                req = {
                    "action": "authenticate",
                    "username": username,
                    "service": service,
                    "timeout": timeout,
                }
                s.sendall(json.dumps(req).encode() + b"\n")
                raw = s.recv(4096).decode()
                s.close()
                resp = json.loads(raw)
                return resp.get("status") == "success"
            except Exception as e:
                logger.debug(f"Daemon socket auth failed: {e}")
                break

    # Fallback to standalone CLI verify
    cmd = [
        str(Path(__file__).resolve().parent.parent.parent.parent / "bin" / "glimpse"),
        "verify",
        "--timeout", str(timeout)
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def protect_app(app_cmd: str, alias: Optional[str] = None) -> bool:
    """
    Wrap an application executable with a FaceID guard in ~/.local/bin/.
    """
    LOCAL_BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_path = shutil.which(app_cmd)
    if not target_path:
        print(f"[!] Error: Could not find application '{app_cmd}' in system PATH.")
        return False

    name = alias or Path(target_path).name
    wrapper_path = LOCAL_BIN_DIR / name

    if wrapper_path.resolve() == Path(target_path).resolve():
        # Avoid direct overwrite if binary is already in ~/.local/bin
        wrapper_path = LOCAL_BIN_DIR / f"{name}-secure"

    glimpse_bin = Path(__file__).resolve().parent.parent.parent.parent / "bin" / "glimpse"

    wrapper_content = f"""#!/usr/bin/env bash
# Glimpse FaceID Protected Application Wrapper
echo "[*] Authenticating with FaceID to launch '{name}'..."
if "{glimpse_bin}" verify --timeout 3.0; then
    exec "{target_path}" "$@"
else
    echo "[!] FaceID authentication failed. Launch aborted."
    exit 1
fi
"""
    wrapper_path.write_text(wrapper_content)
    wrapper_path.chmod(0o755)

    print(f"[+] SUCCESS: Protected application '{name}'!")
    print(f"    • Wrapper installed at: {wrapper_path}")
    print(f"    • FaceID is now required to launch '{name}'.")
    return True


def unprotect_app(app_cmd: str) -> bool:
    """
    Remove FaceID protection wrapper for an application from ~/.local/bin/.
    """
    name = Path(app_cmd).name
    wrapper_path = LOCAL_BIN_DIR / name

    if not wrapper_path.exists():
        print(f"[!] Error: Application '{name}' is not currently protected in {LOCAL_BIN_DIR}.")
        return False

    try:
        content = wrapper_path.read_text()
    except Exception as e:
        print(f"[!] Error reading '{wrapper_path}': {e}")
        return False

    if "Glimpse FaceID Protected Application Wrapper" not in content:
        print(f"[!] Warning: '{wrapper_path}' is not a Glimpse FaceID wrapper. Aborting for safety.")
        return False

    try:
        wrapper_path.unlink()
        print(f"[+] SUCCESS: Removed FaceID protection for '{name}'.")
        print(f"    • Deleted wrapper: {wrapper_path}")
        print(f"    • '{name}' will now launch normally without biometric authentication.")
        return True
    except Exception as e:
        print(f"[!] Error deleting wrapper '{wrapper_path}': {e}")
        return False



def lock_folder(folder_path: str) -> bool:
    """
    Lock a directory by revoking read/write/traversal permissions until FaceID unlocked.
    """
    p = Path(folder_path).resolve()
    if not p.exists() or not p.is_dir():
        print(f"[!] Error: Directory '{folder_path}' does not exist.")
        return False

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    records = {}
    if PROTECTED_FOLDERS_FILE.exists():
        try:
            records = json.loads(PROTECTED_FOLDERS_FILE.read_text())
        except Exception:
            records = {}

    current_mode = stat.S_IMODE(p.stat().st_mode)
    records[str(p)] = {"original_mode": current_mode, "locked_at": str(p)}

    # Revoke all permissions (000)
    p.chmod(0o000)

    PROTECTED_FOLDERS_FILE.write_text(json.dumps(records, indent=2))
    print(f"[+] SUCCESS: Locked folder '{p}' (Permissions set to 0000).")
    print(f"    • Access blocked until unlocked with: glimpse unlock \"{p}\"")
    subprocess.run(["notify-send", "-i", "security-high", "Glimpse FaceID", f"Locked folder: {p.name}"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    return True


def unlock_folder(folder_path: str) -> bool:
    """
    Unlock a directory after successful FaceID verification.
    """
    p = Path(folder_path).resolve()
    if not p.exists() and not (PROTECTED_FOLDERS_FILE.exists()):
        print(f"[!] Error: Directory '{folder_path}' not found.")
        return False

    records = {}
    if PROTECTED_FOLDERS_FILE.exists():
        try:
            records = json.loads(PROTECTED_FOLDERS_FILE.read_text())
        except Exception:
            records = {}

    print(f"[*] Verifying FaceID to unlock folder '{p}'...")
    if not verify_face_auth(timeout=3.0, service="folder_protection"):
        print("[!] FaceID authentication failed. Folder remains locked.")
        subprocess.run(["notify-send", "-i", "security-low", "Glimpse FaceID", f"Authentication failed. Folder '{p.name}' remains locked."], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        return False

    # Restore original permissions
    orig_mode = records.get(str(p), {}).get("original_mode", 0o755)
    try:
        p.chmod(orig_mode)
        if str(p) in records:
            del records[str(p)]
            PROTECTED_FOLDERS_FILE.write_text(json.dumps(records, indent=2))
        print(f"[+] SUCCESS: Unlocked folder '{p}' (Permissions restored to {oct(orig_mode)}).")
        subprocess.run(["notify-send", "-i", "security-high", "Glimpse FaceID", f"Unlocked folder: {p.name}"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[!] Error restoring permissions on '{p}': {e}")
        return False


def run_guarded(command: List[str]) -> int:
    """
    Execute any command only if FaceID succeeds.
    """
    if not command:
        print("[!] Error: No command specified to run.")
        return 1

    print(f"[*] Authenticating with FaceID to execute: {' '.join(command)}")
    if verify_face_auth(timeout=3.0):
        print("[+] Authentication successful. Launching command...")
        res = subprocess.run(command)
        return res.returncode
    else:
        print("[!] FaceID authentication failed. Execution blocked.")
        return 1
