"""
Glimpse Daemon (glimpsed).
Central privileged service managing camera hardware, biometric evaluation,
policy enforcement, and IPC communication with PAM and UI Overlay clients.
"""

from __future__ import annotations
import os
import sys
import json
import time
import signal
import socket
import select
import logging
import argparse
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set

from glimpse.engine.detector import YuNetDetector
from glimpse.engine.embedder import FaceEmbedder
from glimpse.engine.matcher import BiometricMatcher
from glimpse.storage.vault import BiometricVault
from glimpse.daemon.session import AuthSession, AuthResult
from glimpse.policy.engine import PolicyEngine, ServicePolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [glimpsed] %(message)s")
logger = logging.getLogger("glimpse.daemon")

MODELS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "models"
DETECTOR_PATH = str(MODELS_DIR / "face_detection_yunet_2023mar.onnx")
EMBEDDER_PATH = str(MODELS_DIR / "w600k_mbf.onnx")

class GlimpseDaemon:
    """Core daemon managing authentication socket, policy engine, and UI event broadcast."""

    def __init__(
        self,
        socket_path: Optional[str] = None,
        event_socket_path: Optional[str] = None,
        device_index: int = 0,
        threshold: float = 0.450,
        system_mode: bool = False,
    ):
        if socket_path:
            self.socket_path = Path(socket_path)
        else:
            if os.geteuid() == 0 or system_mode:
                self.socket_path = Path("/run/glimpse/glimpse.sock")
            else:
                self.socket_path = Path.home() / ".local" / "share" / "glimpse" / "glimpse.sock"

        if event_socket_path:
            self.event_socket_path = Path(event_socket_path)
        else:
            if os.geteuid() == 0 or system_mode:
                self.event_socket_path = Path("/run/glimpse/events.sock")
            else:
                self.event_socket_path = Path.home() / ".local" / "share" / "glimpse" / "events.sock"

        self.device_index = device_index
        self.threshold = threshold
        self.running = False

        # Prepare directory
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize Policy Engine
        self.policy_engine = PolicyEngine()

        # Initialize engine & vault
        logger.info("Initializing Face Engine on CPU...")
        self.detector = YuNetDetector(DETECTOR_PATH)
        self.embedder = FaceEmbedder(EMBEDDER_PATH)
        self.matcher = BiometricMatcher(threshold=self.threshold)
        self.vault = BiometricVault()

        # UI event subscribers
        self.event_clients: Set[socket.socket] = set()
        self.event_lock = threading.Lock()

        # Auth lock to ensure only one auth session accesses camera at a time
        self.auth_lock = threading.Lock()

    def broadcast_event(self, event_name: str, payload: dict) -> None:
        """Broadcast an event JSON to all connected UI overlay clients."""
        msg = json.dumps({"event": event_name, **payload}) + "\n"
        data = msg.encode("utf-8")

        with self.event_lock:
            disconnected = set()
            for client in self.event_clients:
                try:
                    client.sendall(data)
                except Exception:
                    disconnected.add(client)
            for c in disconnected:
                self.event_clients.discard(c)
                try:
                    c.close()
                except Exception:
                    pass

    def _event_server_loop(self, event_srv: socket.socket) -> None:
        """Accepts UI overlay connections that want to receive visual animation events."""
        event_srv.setblocking(False)
        while self.running:
            readable, _, _ = select.select([event_srv], [], [], 0.5)
            if readable:
                try:
                    conn, _ = event_srv.accept()
                    with self.event_lock:
                        self.event_clients.add(conn)
                    logger.debug("New UI overlay client connected to events stream.")
                except Exception:
                    break

    def handle_auth_request(self, req: dict) -> dict:
        """Process an authentication request from PAM through the Policy Engine."""
        username = req.get("username", "")
        timeout = float(req.get("timeout", 2.5))
        service = req.get("service", "sudo")

        if not username:
            return {"status": "error", "message": "missing username"}

        # 1. Evaluate Security Policy
        policy = self.policy_engine.evaluate(service, username)
        if not policy.is_face_allowed:
            logger.info(f"Policy rejection: service '{service}' forbids face authentication. Falling back to password.")
            return {
                "status": "failure",
                "reason": "policy_denied",
                "allow_password_fallback": policy.allow_password_fallback
            }

        effective_timeout = min(timeout, policy.max_timeout_sec) if policy.max_timeout_sec > 0 else timeout

        # 2. Attempt to acquire camera auth lock
        if not self.auth_lock.acquire(blocking=False):
            logger.warning(f"Auth requested for '{username}' but camera session is busy")
            return {"status": "failure", "reason": "camera_busy"}

        try:
            session = AuthSession(
                detector=self.detector,
                embedder=self.embedder,
                matcher=self.matcher,
                vault=self.vault,
                device_index=self.device_index,
            )
            result: AuthResult = session.authenticate(
                username=username,
                timeout_seconds=effective_timeout,
                min_similarity=policy.min_similarity,
                liveness_required=policy.liveness_required,
                event_callback=self.broadcast_event,
            )

            if result.success:
                return {
                    "status": "success",
                    "username": username,
                    "similarity": result.similarity,
                    "duration_ms": result.duration_ms,
                }
            else:
                return {
                    "status": "failure",
                    "username": username,
                    "reason": result.reason,
                    "similarity": result.similarity,
                    "duration_ms": result.duration_ms,
                    "allow_password_fallback": policy.allow_password_fallback,
                }
        finally:
            self.auth_lock.release()

    def start(self) -> None:
        """Run the daemon main loop."""
        self.running = True

        # Clean old socket files
        if self.socket_path.exists():
            self.socket_path.unlink()
        if self.event_socket_path.exists():
            self.event_socket_path.unlink()

        # Create main auth socket
        main_srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        main_srv.bind(str(self.socket_path))
        main_srv.listen(5)
        os.chmod(self.socket_path, 0o666) # allow client access

        # Create event broadcaster socket
        event_srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        event_srv.bind(str(self.event_socket_path))
        event_srv.listen(5)
        os.chmod(self.event_socket_path, 0o666)

        event_thread = threading.Thread(target=self._event_server_loop, args=(event_srv,), daemon=True)
        event_thread.start()

        logger.info(f"glimpsed listening on: {self.socket_path}")
        logger.info(f"glimpsed events stream: {self.event_socket_path}")

        main_srv.setblocking(False)

        while self.running:
            try:
                readable, _, _ = select.select([main_srv], [], [], 0.5)
                if not readable:
                    continue

                conn, _ = main_srv.accept()
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in daemon loop: {e}")

        self.stop()
        main_srv.close()
        event_srv.close()

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            data = conn.recv(4096)
            if not data:
                return
            req = json.loads(data.decode("utf-8"))
            action = req.get("action", "")

            if action == "authenticate":
                resp = self.handle_auth_request(req)
            elif action == "ping":
                resp = {"status": "pong", "time": time.time()}
            else:
                resp = {"status": "error", "message": f"unknown action {action}"}

            conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
        except Exception as e:
            logger.error(f"Client handling error: {e}")
        finally:
            conn.close()

    def stop(self) -> None:
        self.running = False
        if self.socket_path.exists():
            try: self.socket_path.unlink()
            except OSError: pass
        if self.event_socket_path.exists():
            try: self.event_socket_path.unlink()
            except OSError: pass
        logger.info("glimpsed stopped.")

def main():
    parser = argparse.ArgumentParser(description="Glimpse Authentication Daemon")
    parser.add_argument("--system", action="store_true", help="Run in system root mode (/run/glimpse/)")
    parser.add_argument("--socket", type=str, default=None, help="Custom socket path")
    parser.add_argument("--events-socket", type=str, default=None, help="Custom events socket path")
    parser.add_argument("--device", type=int, default=0, help="Camera device index")
    args = parser.parse_args()

    daemon = GlimpseDaemon(
        socket_path=args.socket,
        event_socket_path=args.events_socket,
        device_index=args.device,
        system_mode=args.system,
    )

    def _signal_handler(sig, frame):
        logger.info("Received termination signal, stopping daemon...")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    daemon.start()

if __name__ == "__main__":
    main()
