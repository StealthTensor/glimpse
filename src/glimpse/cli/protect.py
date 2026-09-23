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
import re
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


def find_real_binary(app_cmd: str) -> Optional[str]:
    """Resolve the genuine system executable for an application, bypassing any wrappers."""
    # 1. Search PATH excluding LOCAL_BIN_DIR
    raw_path = os.environ.get("PATH", "")
    filtered_dirs = [d for d in raw_path.split(os.path.pathsep) if d and Path(d).resolve() != LOCAL_BIN_DIR.resolve()]
    clean_path = os.path.pathsep.join(filtered_dirs)
    system_target = shutil.which(app_cmd, path=clean_path)
    if system_target and Path(system_target).resolve() != (LOCAL_BIN_DIR / Path(app_cmd).name).resolve():
        return system_target

    # 2. If already wrapped in LOCAL_BIN_DIR, inspect existing wrapper for target binary
    wrapper_path = LOCAL_BIN_DIR / Path(app_cmd).name
    if wrapper_path.exists():
        try:
            content = wrapper_path.read_text()
            m = re.search(r'exec\s+"([^"]+)"', content)
            if m:
                nested_target = m.group(1)
                if nested_target != str(wrapper_path) and os.path.exists(nested_target):
                    return nested_target
        except Exception:
            pass

    # 3. Standard fallback
    target = shutil.which(app_cmd)
    if target and Path(target).resolve() != (LOCAL_BIN_DIR / Path(app_cmd).name).resolve():
        return target
    return None


def protect_app(app_cmd: str, alias: Optional[str] = None) -> bool:
    """
    Wrap an application executable with a FaceID guard in ~/.local/bin/.
    """
    LOCAL_BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_path = find_real_binary(app_cmd)
    if not target_path:
        print(f"[!] Error: Could not find application '{app_cmd}' in system PATH.")
        return False

    name = alias or Path(app_cmd).name
    wrapper_path = LOCAL_BIN_DIR / name

    # Also clean up any accidental name-secure leftover
    secure_dup = LOCAL_BIN_DIR / f"{name}-secure"
    if secure_dup.exists():
        try:
            secure_dup.unlink()
        except Exception:
            pass

    glimpse_bin = shutil.which("glimpse") or str(Path(__file__).resolve().parent.parent.parent.parent / "bin" / "glimpse")

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
    print(f"    • Target binary: {target_path}")
    print(f"    • FaceID is now required to launch '{name}'.")
    return True


def unprotect_app(app_cmd: str) -> bool:
    """
    Remove FaceID protection wrapper for an application from ~/.local/bin/.
    """
    name = Path(app_cmd).name
    wrapper_path = LOCAL_BIN_DIR / name
    secure_dup = LOCAL_BIN_DIR / f"{name}-secure"

    removed_any = False

    for target in [wrapper_path, secure_dup]:
        if not target.exists():
            continue

        try:
            content = target.read_text()
        except Exception as e:
            print(f"[!] Error reading '{target}': {e}")
            continue

        if ("Glimpse FaceID Protected Application Wrapper" not in content and
            "Sentinel FaceID Protected Application Wrapper" not in content):
            print(f"[!] Warning: '{target}' is not a Glimpse/Sentinel FaceID wrapper. Aborting for safety.")
            continue

        try:
            target.unlink()
            print(f"[+] SUCCESS: Removed FaceID protection for '{target.name}'.")
            print(f"    • Deleted wrapper: {target}")
            removed_any = True
        except Exception as e:
            print(f"[!] Error deleting wrapper '{target}': {e}")

    if removed_any:
        print(f"    • '{name}' will now launch normally without biometric authentication.")
        return True
    else:
        print(f"[!] Error: Application '{name}' is not currently protected in {LOCAL_BIN_DIR}.")
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
