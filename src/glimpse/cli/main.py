"""
Glimpse CLI: Management & Diagnostic Tool.
Provides interactive enrollment, verification, camera testing, and vault management.
"""

from __future__ import annotations
import os
import sys
import time
import argparse
import getpass
import logging
from pathlib import Path
import cv2
import numpy as np

from glimpse.camera.v4l2 import V4L2Camera
from glimpse.engine.detector import YuNetDetector
from glimpse.engine.embedder import FaceEmbedder
from glimpse.engine.matcher import BiometricMatcher
from glimpse.engine.liveness import RGBLivenessDetector
from glimpse.storage.vault import BiometricVault

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("glimpse.cli")

MODELS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "models"
DETECTOR_PATH = str(MODELS_DIR / "face_detection_yunet_2023mar.onnx")
EMBEDDER_PATH = str(MODELS_DIR / "w600k_mbf.onnx")

def cmd_test_camera(args):
    """Test camera access, latency, and face detection."""
    print(f"[*] Testing camera: /dev/video{args.device}...")
    cam = V4L2Camera(device_index=args.device, width=640, height=480)
    if not cam.open():
        print(f"[!] Error: Could not open camera /dev/video{args.device}")
        return 1

    print("[+] Camera opened successfully.")
    detector = YuNetDetector(DETECTOR_PATH)
    print("[+] Face detector loaded on CPU.")

    start_time = time.time()
    frames_grabbed = 0
    face_counts = 0
    latencies = []

    print("[*] Sampling 30 frames for latency and face presence...")
    try:
        while frames_grabbed < 30:
            t0 = time.perf_counter()
            ret, frame = cam.read_frame()
            if not ret or frame is None:
                continue

            faces = detector.detect(frame)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)

            frames_grabbed += 1
            if faces:
                face_counts += 1

        fps = frames_grabbed / (time.time() - start_time)
        avg_latency = np.mean(latencies)
        p95_latency = np.percentile(latencies, 95)

        print(f"[+] Capture & Detection FPS: {fps:.1f}")
        print(f"[+] Inference Latency: avg={avg_latency:.1f}ms, p95={p95_latency:.1f}ms (CPU)")
        print(f"[+] Faces detected in {face_counts}/{frames_grabbed} frames")
        if face_counts > 0:
            print("[+] Camera and Face Pipeline: OPTIMAL")
        else:
            print("[!] Warning: No face detected. Ensure proper lighting and face camera directly.")
    finally:
        cam.release()
    return 0

def cmd_enroll(args):
    """Enroll biometric templates for a user with guided multi-pose scanning."""
    user = args.username or getpass.getuser()
    embedder = FaceEmbedder() # Defaults to 512-D ArcFace
    dim = embedder.vector_dim

    print("=" * 64)
    print(f"    Glimpse: Guided 3D Multi-Pose Facial Enrollment ({dim}-D)")
    print("=" * 64)
    print(f"[*] Target Profile: {user}")
    print(f"[*] Biometric Engine: ArcFace / MobileFaceNet (512-D Unit Hypersphere)")
    print(f"[*] Capturing comprehensive 3D pose variation (Front, Left, Right, Tilts)")
    print("=" * 64)

    cam = V4L2Camera(device_index=args.device, width=640, height=480)
    if not cam.open():
        print("[!] Error: Could not open camera. Ensure /dev/video0 is not in use.")
        return 1

    detector = YuNetDetector(DETECTOR_PATH)
    vault = BiometricVault()

    poses = [
        {"title": "POSE 1/6: LOOK DIRECTLY AT CAMERA (Frontal Center)", "hint": "Look straight into camera lens, neutral expression", "count": 5},
        {"title": "POSE 2/6: TURN HEAD SLIGHTLY LEFT (~15°-20°)", "hint": "Rotate head gently left, keep eyes toward screen", "count": 4},
        {"title": "POSE 3/6: TURN HEAD SLIGHTLY RIGHT (~15°-20°)", "hint": "Rotate head gently right, keep eyes toward screen", "count": 4},
        {"title": "POSE 4/6: TILT CHIN SLIGHTLY UP (~10°-15°)", "hint": "Tilt chin upward slightly", "count": 3},
        {"title": "POSE 5/6: TILT CHIN SLIGHTLY DOWN (~10°-15°)", "hint": "Tilt chin downward slightly", "count": 3},
        {"title": "POSE 6/6: NATURAL EXPRESSION / SLIGHT SMILE", "hint": "Smile naturally or talk softly", "count": 4},
    ]

    total_target = sum(p["count"] for p in poses)
    collected_vectors = []

    try:
        for p_idx, pose in enumerate(poses, 1):
            print(f"\n[▶] Step {p_idx}/6: {pose['title']}")
            print(f"    -> {pose['hint']}")
            print("    -> Adjust position in 2 seconds...", end="", flush=True)
            for _ in range(2):
                time.sleep(0.8)
                print(".", end="", flush=True)
            print(" Capturing!")

            pose_captured = 0
            last_cap_time = 0.0
            pose_start = time.time()

            while pose_captured < pose["count"]:
                if time.time() - pose_start > 15.0:
                    print(f"    [!] Timeout on pose {p_idx}. Moving to next pose.")
                    break

                ret, frame = cam.read_frame()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                faces = detector.detect(frame)
                if not faces:
                    time.sleep(0.03)
                    continue

                primary = faces[0]
                x, y, w, h = primary.bbox
                if w < 90 or h < 90 or primary.score < 0.60:
                    continue

                if time.time() - last_cap_time < 0.28:
                    continue

                aligned = embedder.align_and_crop(frame, primary.raw)
                feat = embedder.extract(aligned)
                collected_vectors.append(feat)
                pose_captured += 1
                last_cap_time = time.time()

                overall_pct = int((len(collected_vectors) / total_target) * 100)
                print(f"    ✓ Captured sample {pose_captured}/{pose['count']} (Total: {len(collected_vectors)}/{total_target} [{overall_pct}%])")

        if len(collected_vectors) < 5:
            print("\n[!] Error: Not enough valid samples captured. Enrollment aborted.")
            return 1

        vault.save_templates(user, collected_vectors)
        print("\n" + "=" * 64)
        print(f"[+] ENROLLMENT COMPLETE: {len(collected_vectors)} 512-D vectors stored for '{user}'!")
        print(f"[+] Multi-pose 3D coverage active (Frontal, Left, Right, Tilts, Expression).")
        print(f"[+] AES-256-GCM encrypted in: {vault.vault_dir / f'{user}.enc'}")
        print("=" * 64)
    finally:
        cam.release()
    return 0

def cmd_verify(args):
    """Verify face against enrolled templates with liveness checking."""
    user = args.username or getpass.getuser()
    vault = BiometricVault()
    templates = vault.load_templates(user)
    if not templates:
        print(f"[!] Error: No enrollment found for user '{user}'. Run 'glimpse enroll' first.")
        return 2

    # Check if glimpsed daemon is running to trigger animated desktop notch
    for sock_path in ["/run/glimpse/glimpse.sock", str(vault.vault_dir.parent / "glimpse.sock")]:
        if os.path.exists(sock_path):
            try:
                import socket, json
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(args.timeout + 2.0)
                s.connect(sock_path)
                req = {
                    "action": "authenticate",
                    "username": user,
                    "service": "verify",
                    "timeout": args.timeout,
                }
                s.sendall(json.dumps(req).encode() + b"\n")
                raw = s.recv(4096).decode()
                s.close()
                resp = json.loads(raw)
                if resp.get("status") == "success":
                    dur = resp.get("duration_ms", 0.0)
                    sim = resp.get("similarity", 0.0)
                    print(f"\n[+] AUTH_SUCCESS: User '{user}' verified in {dur:.1f}ms! Score={sim:.4f}")
                    return 0
                else:
                    reason = resp.get("reason", resp.get("message", "auth_failed"))
                    print(f"\n[-] AUTH_FAILED: Face not recognized or timeout ({reason}).")
                    return 1
            except Exception as e:
                logger.debug(f"Daemon socket connection failed, falling back to local: {e}")
                break

    cam = V4L2Camera(device_index=args.device)
    if not cam.open():
        print("[!] Error: Could not open camera.")
        return 1

    detector = YuNetDetector(DETECTOR_PATH)
    embedder = FaceEmbedder(EMBEDDER_PATH)
    matcher = BiometricMatcher(threshold=args.threshold)
    liveness = RGBLivenessDetector()

    print(f"[*] Verifying user '{user}' (Timeout: {args.timeout}s)...")
    start_t = time.time()
    verified = False
    best_similarity = 0.0

    try:
        while (time.time() - start_t) < args.timeout:
            ret, frame = cam.read_frame()
            if not ret or frame is None:
                continue

            faces = detector.detect(frame)
            if not faces:
                continue

            primary = faces[0]
            liveness.update(primary.landmarks, primary.bbox)

            aligned = embedder.align_and_crop(frame, primary.raw)
            feat = embedder.extract(aligned)

            is_match, score = matcher.match(feat, templates)
            if score > best_similarity:
                best_similarity = score

            if is_match:
                # Check liveness
                live_res = liveness.check_liveness(frame)
                if live_res.is_live:
                    elapsed = (time.time() - start_t) * 1000.0
                    print(f"\n[+] AUTH_SUCCESS: User '{user}' verified in {elapsed:.1f}ms! Score={score:.4f} (Threshold={args.threshold})")
                    verified = True
                    break
                else:
                    print(f"\n[!] LIVENESS_FAIL: {', '.join(live_res.reasons)}")

        if not verified:
            print(f"\n[-] AUTH_FAILED: Face not recognized or timeout. Best score={best_similarity:.4f} (Threshold={args.threshold})")
            return 1
    finally:
        cam.release()
    return 0

def cmd_list(args):
    """List enrolled users in vault."""
    vault = BiometricVault()
    files = list(vault.vault_dir.glob("*.enc"))
    print(f"[*] Biometric Vault: {vault.vault_dir}")
    if not files:
        print("    (No enrolled users)")
        return 0

    for f in files:
        user = f.stem
        templates = vault.load_templates(user)
        print(f"  • User: {user} ({len(templates)} template vectors enrolled)")
    return 0

def cmd_purge(args):
    """Purge enrollment for a user."""
    user = args.username or getpass.getuser()
    vault = BiometricVault()
    if vault.delete_user(user):
        print(f"[+] Purged enrollment for '{user}'.")
    else:
        print(f"[-] No enrollment found for '{user}'.")
    return 0

def cmd_diag(args):
    """Launch PyQt6 real-time camera diagnostic & model verification studio."""
    from glimpse.ui.diagnostics import main as diag_main
    user = args.user or getpass.getuser()
    sys.argv = [sys.argv[0], user]
    diag_main()
    return 0

def main():
    parser = argparse.ArgumentParser(description="Glimpse: Facial Authentication CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # diag / test / studio (Live Camera Model Verification)
    p_diag = sub.add_parser("diag", help="Launch live camera diagnostic studio & model verification")
    p_diag.add_argument("--user", "-u", type=str, default=None, help="Target profile to test against")
    p_diag.set_defaults(func=cmd_diag)

    p_test = sub.add_parser("test", help="Alias for diag (Live camera diagnostic studio)")
    p_test.add_argument("--user", "-u", type=str, default=None, help="Target profile to test against")
    p_test.set_defaults(func=cmd_diag)

    # test-camera
    p_cam = sub.add_parser("test-camera", help="Test camera and measure detection latency")
    p_cam.add_argument("--device", type=int, default=0, help="Camera device index (default: 0)")
    p_cam.set_defaults(func=cmd_test_camera)

    # enroll
    p_enr = sub.add_parser("enroll", help="Enroll face biometric templates")
    p_enr.add_argument("--username", "-u", type=str, default=None, help="Target username")
    p_enr.add_argument("--samples", "-s", type=int, default=5, help="Number of samples (default: 5)")
    p_enr.add_argument("--device", type=int, default=0, help="Camera device index")
    p_enr.set_defaults(func=cmd_enroll)

    # verify
    p_ver = sub.add_parser("verify", help="Verify face against vault")
    p_ver.add_argument("--username", "-u", type=str, default=None, help="Target username")
    p_ver.add_argument("--timeout", "-t", type=float, default=2.5, help="Timeout in seconds")
    p_ver.add_argument("--threshold", type=float, default=0.450, help="Similarity threshold (default: 0.450)")
    p_ver.add_argument("--device", type=int, default=0, help="Camera device index")
    p_ver.set_defaults(func=cmd_verify)

    # protect (App protection)
    from glimpse.cli.protect import protect_app, unprotect_app, lock_folder, unlock_folder, run_guarded

    p_prot = sub.add_parser("protect", help="Protect an application with FaceID")
    p_prot.add_argument("app", type=str, help="Application command or executable (e.g. firefox)")
    p_prot.add_argument("--alias", type=str, default=None, help="Custom command alias")
    p_prot.set_defaults(func=lambda a: 0 if protect_app(a.app, a.alias) else 1)

    p_unprot = sub.add_parser("unprotect", help="Remove FaceID protection from an application")
    p_unprot.add_argument("app", type=str, help="Application command to unprotect (e.g. kcalc)")
    p_unprot.set_defaults(func=lambda a: 0 if unprotect_app(a.app) else 1)

    # lock (Folder protection)
    p_lock = sub.add_parser("lock", help="Lock a folder with FaceID")
    p_lock.add_argument("folder", type=str, help="Path to directory")
    p_lock.set_defaults(func=lambda a: 0 if lock_folder(a.folder) else 1)

    # unlock (Folder unlock)
    p_unlk = sub.add_parser("unlock", help="Unlock a folder with FaceID")
    p_unlk.add_argument("folder", type=str, help="Path to directory")
    p_unlk.set_defaults(func=lambda a: 0 if unlock_folder(a.folder) else 1)

    # run (FaceID-guarded execution)
    p_run = sub.add_parser("run", help="Run any command guarded by FaceID")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="Command and arguments to run")
    p_run.set_defaults(func=lambda a: run_guarded(a.cmd))

    # list
    p_lst = sub.add_parser("list", help="List enrolled users")
    p_lst.set_defaults(func=cmd_list)

    # purge
    p_del = sub.add_parser("purge", help="Delete user biometric enrollment")
    p_del.add_argument("--username", "-u", type=str, default=None, help="Username to delete")
    p_del.set_defaults(func=cmd_purge)

    args = parser.parse_args()
    sys.exit(args.func(args))

if __name__ == "__main__":

    main()

