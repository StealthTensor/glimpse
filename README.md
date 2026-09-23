# Glimpse 👁️

[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%7C%20Wayland%20%7C%20X11-blue?logo=linux)](https://github.com/StealthTensor/glimpse)
[![Desktop: KDE Plasma 6](https://img.shields.io/badge/KDE-Plasma%206-1d99f3?logo=kde)](https://kde.org)
[![Engine: ArcFace 512--D](https://img.shields.io/badge/Embedding-ArcFace%20512--D-orange)](https://github.com/deepinsight/insightface)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-brightgreen?logo=python)](https://python.org)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-purple.svg)](LICENSE)

A local-first facial authentication system for Linux that doesn't feel like a science fair project.

Glimpse brings fluid, Apple-style facial authentication to Linux desktops. It plugs directly into PAM for passwordless `sudo`, integrates into KDE Plasma 6's Wayland lockscreen with a native drop-down notch, hooks Polkit admin prompts (like Dolphin's root actions), and lets you gate sensitive folders and apps behind your face.

No cloud telemetry. No IR hardware required. No 10-second delays while a heavy neural net wakes up. Just a 400ms glance and you're in.

---

## Highlights & Demo

<p align="center">
  <img src="assets/unlockstatic.png" alt="Glimpse Apple FaceID Notch" width="180">
</p>

- ⚡ **Zero-Click KDE Lockscreen**: Native Wayland drop-down notch glides down and unlocks without touching the keyboard.
- 🛡️ **Instant Sudo & Polkit**: ~480ms glance authenticates terminal `sudo` and Dolphin administrative actions.
- 🌙 **Hardware Autobrightness (Low-Light Assist)**: Direct sysfs backlight control (`/sys/class/backlight`) boosts screen luminance in pitch-black rooms so camera can detect your face even in total darkness.
- 🔒 **Biometric App & Vault Guard**: Gate any app (`glimpse protect kcalc`) or folder (`glimpse lock ~/vault`) behind facial recognition.
- 🚀 **Sub-12ms ArcFace Inference**: 512-D hypersphere embeddings running on CPU with AVX2.



## Architecture & Pipeline

```
[ Web Camera: /dev/video0 ]
            │  (V4L2 30 FPS MJPEG capture)
            ▼
[ YuNet Face Detector ]
            │  (32ms inference on CPU, extracts 5 facial landmarks)
            ▼
[ 5-Point Affine Aligner ]
            │  (Normalizes roll, pitch, yaw into canonical 112x112 crop)
            ▼
[ ArcFace 512-D Embedder ]
            │  (11.9ms inference on CPU AVX2, outputs unit L2 vector)
            ▼
[ Temporal Voting Filter ]
            │  (Requires 3 consecutive matching frames >= 0.450 similarity)
            ▼
    ┌───────┴─────────────────────────────────────────┐
    ▼                                                 ▼
[ glimpsed (UNIX Socket Daemon) ]         [ Dynamic Bezel Notch ]
/run/glimpse/glimpse.sock                 Hardware-accelerated QML overlay
    │                                                 │
    ├─► sudo (Terminal Elevation)                     ├─► KDE Lockscreen (Zero-click)
    ├─► Polkit (Dolphin Admin / pkexec)               ├─► Desktop App Launch Notch
    ├─► SDDM (Cold Boot Login)                        └─► Dark Room Screen Illuminator
    └─► App & Folder Protection
```

### How the pieces fit together

1. **Detection & Alignment**: When auth triggers, the camera grabs frames at 30 FPS. YuNet locates the face bounding box and five primary landmarks (pupils, nose tip, mouth corners). An affine transformation warps the face to a canonical 112x112 frontal view to eliminate head tilt.
2. **512-D ArcFace Embedding**: The aligned crop runs through MobileFaceNet ArcFace. Unlike legacy 128-D Euclidean models that fail when your lighting changes, ArcFace projects features onto a hypersphere with an angular margin penalty, yielding high cluster separation.
3. **Temporal Anti-Impostor Voting**: To prevent false positives from motion blur, sudden shadows, or camera noise, the daemon rejects single-frame lucky matches. It requires **three consecutive matching frames** above threshold before approving authentication.
4. **Thin C PAM Adapter**: `pam_glimpse.so` is a lean C shared library. It contains zero heavy dependencies and zero ML code—it just talks to `/run/glimpse/glimpse.sock` over a UNIX socket. If the daemon is inactive, the camera is unplugged, or your face isn't recognized, PAM immediately falls back to your standard password prompt. No hangs, no lockouts.

---

## Real-world Benchmarks

Measured on an HP Victus 15 (Intel Core i5-13500H, HP Wide Vision 720p HD Camera, Kubuntu 25.10 / KDE Plasma 6.4 Wayland):

| Component | Architecture / Model | Device | Latency |
| :--- | :--- | :--- | :--- |
| Face Detection | YuNet (ONNX) | CPU (AVX2) | 32.6 ms |
| Face Alignment | 5-Point Affine 112x112 | CPU | 1.2 ms |
| Feature Extraction | ArcFace MobileFaceNet 512-D | CPU (AVX2) | **11.9 ms** |
| Vector Matching | Cosine Dot Product (23 templates) | CPU | 0.1 ms |
| **Total Auth Duration** | **From trigger to desktop reveal** | **Live Camera** | **~480 ms** |
| Video Pipeline | V4L2 MJPEG `/dev/video0` | Hardware | 30.6 FPS |

The daemon idles at ~50 MB RAM and releases the camera device the millisecond authentication completes.

---

## Features

### Zero-Click Lockscreen
KDE's lockscreen (`kscreenlocker_greet`) normally replaces passwordless PAM success with an awkward "Unlock" button, forcing you to press Enter twice. Glimpse hooks directly into the greeter QML: the notch stays hidden behind the clock, glides down when you interact, plays the FaceID checkmark upon recognition, and dismisses straight into your session.

### Terminal Sudo
Run `sudo apt update`. The camera fires up for half a second, the notch drops at the top of your screen, and root permissions are granted without touching the keyboard. If you look away or hit Ctrl+C, the normal `[sudo] password for user:` prompt appears immediately.

### Polkit & Dolphin File Manager Integration
When accessing root directories or mounting encrypted drives in Dolphin, KDE invokes PolicyKit. Glimpse hooks into `/etc/pam.d/polkit-1`, turning administrative elevation into a quick glance.

### Folder Vault & App Guard
- **Right-click folder protection**: Right-click any directory in Dolphin to lock it (`chmod 0000`). Select "Unlock with Glimpse FaceID" to scan your face, restore permissions, and reveal the contents.
- **Application guards**: Protect apps like password managers or browsers (`glimpse protect keepassxc`). When launched from your dock, menu, or terminal, Glimpse verifies your face before executing the binary.
- **Command runner**: Gate any arbitrary CLI command behind biometrics (`glimpse run ssh prod-cluster`).

### Dark Room Screen Illuminator
Regular RGB webcams struggle in pitch-black rooms. When lighting is too low, Glimpse triggers a soft, translucent white vignette with a centered aperture that bounces just enough light off your face for detection to succeed, then fades out smoothly.

---

## Installation

### Prerequisites
- Ubuntu 24.04+, Kubuntu 25.10+, Debian 12+, or Arch Linux
- Python 3.11+
- A working V4L2 webcam (`/dev/video0`)
- Standard build tools (`gcc`, `make`, `pkg-config`)

```bash
# Clone the repository
git clone https://github.com/StealthTensor/glimpse.git
cd glimpse

# Set up Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the installer
sudo ./install.sh
```

The installer will:
1. Compile `pam_glimpse.so` and install it into system security directories.
2. Set up the `glimpsed.service` system daemon.
3. Install the user UI notch service (`glimpse-ui.service`).
4. Configure PAM hooks for `sudo`, `kde`, `sddm`, and `polkit-1` (with automatic `.glimpse_bak` backups).
5. Install the native Dolphin right-click context menu.
6. Patch KDE's lockscreen QML for the zero-click notch experience.

---

## Usage

### 1. Multi-Pose 3D Enrollment
Enroll your face profile with guided poses (Center, Left, Right, Up, Down, Smile) to ensure high similarity from any angle:
```bash
glimpse enroll
```

### 2. Camera Diagnostics
Launch the real-time diagnostic studio to inspect your webcam feed, view facial landmark tracking, check roll/pitch/yaw angles, and test similarity scores live:
```bash
glimpse diag
```

### 3. Verify in Terminal
```bash
glimpse verify
```

### 4. Protect Applications and Folders
```bash
# Protect an application (e.g. calculator, browser, password manager)
glimpse protect kcalc
glimpse protect keepassxc

# Remove protection from an application
glimpse unprotect kcalc

# Lock a directory
glimpse lock ~/my_vault

# Unlock a directory
glimpse unlock ~/my_vault

# Run any command gated behind your face
glimpse run ssh user@remote-box
```

---

## Configuration

Security policy is defined in `config/policy.yaml`:

```yaml
version: "1.0"

default_policy:
  methods: [face, password]
  liveness_required: true
  min_similarity: 0.450
  max_timeout_sec: 2.5
  allow_password_fallback: true

services:
  sudo:
    max_timeout_sec: 2.5
    min_similarity: 0.450

  kde:
    max_timeout_sec: 3.0
    min_similarity: 0.450

  polkit-1:
    max_timeout_sec: 3.0
    min_similarity: 0.450

  sddm:
    max_timeout_sec: 3.5
    min_similarity: 0.480

  su:
    methods: [password] # High-risk: password strictly enforced
```

Thresholds, timeouts, and service policies can be adjusted live without recompilation.

---

## Uninstallation

To revert all changes cleanly:
```bash
sudo ./uninstall.sh
```
This restores all original PAM configurations from backups, stops and removes systemd services, cleans up binaries, and reverts lockscreen QML files back to their pristine states.

---

## License

GPL-3.0 License. See [LICENSE](LICENSE) for details.
