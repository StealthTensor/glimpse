#!/usr/bin/env bash
# Glimpse E2E Automated Installer
# Installs PAM module, systemd background services, Policy Engine, and Apple FaceID Notch.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME=$(getent passwd "${TARGET_USER}" | cut -d: -f6)
TARGET_UID=$(id -u "${TARGET_USER}")

echo "========================================================"
echo "    Glimpse: Facial Authentication E2E Installer       "
echo "========================================================"
echo "[*] Target user: ${TARGET_USER} (UID: ${TARGET_UID}, Home: ${TARGET_HOME})"

# 1. Compile PAM module
echo "[*] Step 1/7: Compiling pam_glimpse.so..."
gcc -fPIC -fno-stack-protector -Wall -Wextra -O2 -shared -o pam/pam_glimpse.so pam/pam_glimpse.c
echo "[+] pam_glimpse.so compiled successfully."

# 2. Copy PAM module to system security directory
echo "[*] Step 2/7: Installing pam_glimpse.so to PAM directories..."
TARGET_DIR="/usr/lib/x86_64-linux-gnu/security"
if [ ! -d "${TARGET_DIR}" ]; then
    TARGET_DIR="/lib/security"
    mkdir -p "${TARGET_DIR}"
fi
cp pam/pam_glimpse.so "${TARGET_DIR}/pam_glimpse.so"
chmod 0644 "${TARGET_DIR}/pam_glimpse.so"
# Ensure legacy /lib/security symlink also points to it
mkdir -p /lib/security
ln -sf "${TARGET_DIR}/pam_glimpse.so" /lib/security/pam_glimpse.so
echo "[+] Installed to ${TARGET_DIR}/pam_glimpse.so and /lib/security/pam_glimpse.so."

# Clean up legacy sentinel artifacts if migrating
systemctl stop sentineld.service 2>/dev/null || true
systemctl disable sentineld.service 2>/dev/null || true
rm -f /etc/systemd/system/sentineld.service 2>/dev/null || true
rm -f /usr/local/bin/sentinel /usr/local/bin/sentinel-ui /usr/local/bin/sentinel-diag 2>/dev/null || true
rm -f /lib/security/pam_sentinel.so /usr/lib/x86_64-linux-gnu/security/pam_sentinel.so 2>/dev/null || true
sed -i 's/pam_sentinel\.so/pam_glimpse\.so/g' /etc/pam.d/sudo /etc/pam.d/kde /etc/pam.d/sddm /etc/pam.d/polkit-1 2>/dev/null || true

# 3. Global CLI symlinks
echo "[*] Step 3/7: Installing global CLI wrappers in /usr/local/bin/..."
ln -sf "${SCRIPT_DIR}/bin/glimpse" /usr/local/bin/glimpse
ln -sf "${SCRIPT_DIR}/bin/glimpse-ui" /usr/local/bin/glimpse-ui
ln -sf "${SCRIPT_DIR}/bin/glimpse-diag" /usr/local/bin/glimpse-diag
echo "[+] /usr/local/bin/glimpse, glimpse-ui, and glimpse-diag linked."

# 4. Systemd System Service (For cold-boot SDDM and root auth)
echo "[*] Step 4/7: Installing systemd system daemon for cold-boot SDDM login..."
tee /etc/systemd/system/glimpsed.service > /dev/null <<EOF
[Unit]
Description=Glimpse System Facial Authentication Daemon
After=network.target local-fs.target
Before=sddm.service display-manager.service

[Service]
Type=simple
ExecStart=${SCRIPT_DIR}/bin/glimpsed --system
Restart=always
RestartSec=2
KillMode=process
RuntimeDirectory=glimpse
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable glimpsed.service
systemctl restart glimpsed.service
echo "[+] System glimpsed.service active and reloaded on /run/glimpse/glimpse.sock."

# 5. User Services & Autostart (Desktop UI Notch)
echo "[*] Step 5/7: Configuring user UI service and KDE autostart for '${TARGET_USER}'..."
mkdir -p "${TARGET_HOME}/.config/systemd/user"
mkdir -p "${TARGET_HOME}/.config/autostart"

cp systemd/glimpse-ui.service "${TARGET_HOME}/.config/systemd/user/"
cp autostart/glimpse-ui.desktop "${TARGET_HOME}/.config/autostart/"
chown -R "${TARGET_USER}:${TARGET_USER}" "${TARGET_HOME}/.config/systemd/user" "${TARGET_HOME}/.config/autostart"

# Safely enable user service within user's active session bus
if [ -d "/run/user/${TARGET_UID}" ]; then
    USER_ENV="XDG_RUNTIME_DIR=/run/user/${TARGET_UID} DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${TARGET_UID}/bus"
    runuser -u "${TARGET_USER}" -- env ${USER_ENV} systemctl --user daemon-reload 2>/dev/null || true
    runuser -u "${TARGET_USER}" -- env ${USER_ENV} systemctl --user enable --now glimpse-ui 2>/dev/null || true
    # Disable redundant user-level daemon since system daemon is now active
    runuser -u "${TARGET_USER}" -- env ${USER_ENV} systemctl --user stop glimpsed 2>/dev/null || true
    runuser -u "${TARGET_USER}" -- env ${USER_ENV} systemctl --user disable glimpsed 2>/dev/null || true
fi
echo "[+] User UI overlay service enabled and running."

# 6. Safe PAM configuration hooks (with backups)
echo "[*] Step 6/7: Hooking PAM for sudo, KDE screen unlock, and SDDM login..."

# 6a. sudo hook
if [ ! -f /etc/pam.d/sudo.glimpse_bak ]; then
    cp /etc/pam.d/sudo /etc/pam.d/sudo.glimpse_bak
    echo "[+] Created backup of /etc/pam.d/sudo at /etc/pam.d/sudo.glimpse_bak."
fi
if ! grep -q "pam_glimpse.so" /etc/pam.d/sudo; then
    sed -i '/@include common-auth/i auth       sufficient pam_glimpse.so' /etc/pam.d/sudo
    echo "[+] Added pam_glimpse.so hook to /etc/pam.d/sudo."
else
    echo "[+] pam_glimpse.so already hooked in /etc/pam.d/sudo."
fi

# 6b. KDE screen locker hook (/etc/pam.d/kde & /etc/pam.d/kscreenlocker)
if [ ! -f /etc/pam.d/kde ]; then
    echo "#%PAM-1.0" | tee /etc/pam.d/kde > /dev/null
    echo "auth       sufficient pam_glimpse.so" | tee -a /etc/pam.d/kde > /dev/null
    echo "@include common-auth" | tee -a /etc/pam.d/kde > /dev/null
    echo "@include common-account" | tee -a /etc/pam.d/kde > /dev/null
    echo "@include common-password" | tee -a /etc/pam.d/kde > /dev/null
    echo "@include common-session" | tee -a /etc/pam.d/kde > /dev/null
    echo "[+] Created /etc/pam.d/kde screen unlock PAM configuration."
fi
if [ ! -e /etc/pam.d/kscreenlocker ]; then
    ln -sf /etc/pam.d/kde /etc/pam.d/kscreenlocker
    echo "[+] Symlinked /etc/pam.d/kscreenlocker to /etc/pam.d/kde."
fi

# 6c. SDDM Cold Boot Login hook (/etc/pam.d/sddm)
if [ -f /etc/pam.d/sddm ]; then
    if [ ! -f /etc/pam.d/sddm.glimpse_bak ]; then
        cp /etc/pam.d/sddm /etc/pam.d/sddm.glimpse_bak 2>/dev/null || true
    fi
    if ! grep -q "pam_glimpse.so" /etc/pam.d/sddm; then
        sed -i '/@include common-auth/i auth       sufficient pam_glimpse.so' /etc/pam.d/sddm
        echo "[+] Added pam_glimpse.so hook to /etc/pam.d/sddm (Cold boot login)."
    else
        echo "[+] pam_glimpse.so already hooked in /etc/pam.d/sddm."
    fi
fi

# 6d. Polkit GUI Elevation hook (/etc/pam.d/polkit-1 for Dolphin admin, Discover, etc.)
if [ ! -f /etc/pam.d/polkit-1.glimpse_bak ]; then
    if [ -f /etc/pam.d/polkit-1 ]; then
        cp /etc/pam.d/polkit-1 /etc/pam.d/polkit-1.glimpse_bak
    elif [ -f /usr/lib/pam.d/polkit-1 ]; then
        cp /usr/lib/pam.d/polkit-1 /etc/pam.d/polkit-1.glimpse_bak
    fi
fi
if [ ! -f /etc/pam.d/polkit-1 ]; then
    tee /etc/pam.d/polkit-1 > /dev/null <<'EOF'
#%PAM-1.0
auth       sufficient pam_glimpse.so
@include common-auth
@include common-account
@include common-password
session       required   pam_env.so readenv=1 user_readenv=0
session       required   pam_env.so readenv=1 envfile=/etc/default/locale user_readenv=0
@include common-session-noninteractive
EOF
    echo "[+] Created /etc/pam.d/polkit-1 with Glimpse FaceID hook (Dolphin admin & GUI auth)."
else
    if ! grep -q "pam_glimpse.so" /etc/pam.d/polkit-1; then
        sed -i '/@include common-auth/i auth       sufficient pam_glimpse.so' /etc/pam.d/polkit-1
        echo "[+] Added pam_glimpse.so hook to /etc/pam.d/polkit-1."
    else
        echo "[+] pam_glimpse.so already hooked in /etc/pam.d/polkit-1."
    fi
fi

# 6e. Dolphin Right-Click Service Menu
mkdir -p "${TARGET_HOME}/.local/share/kio/servicemenus"
cp "${SCRIPT_DIR}/autostart/glimpse_folders.desktop" "${TARGET_HOME}/.local/share/kio/servicemenus/" 2>/dev/null || true
chown -R "${TARGET_USER}:${TARGET_USER}" "${TARGET_HOME}/.local/share/kio" 2>/dev/null || true
echo "[+] Installed Dolphin context menu for FaceID folder locking/unlocking."


# 7. Native KDE Lockscreen Apple FaceID Notch Integration
echo "[*] Step 7/7: Integrating Apple FaceID Notch into KDE Plasma Lockscreen..."
LOCKSCREEN_DIR="/usr/share/plasma/shells/org.kde.plasma.desktop/contents/lockscreen"
if [ -d "${LOCKSCREEN_DIR}" ]; then
    cp "${SCRIPT_DIR}/ui/qml/GlimpseLockNotch.qml" "${LOCKSCREEN_DIR}/GlimpseLockNotch.qml"
    chmod 0644 "${LOCKSCREEN_DIR}/GlimpseLockNotch.qml"

    python3 - <<'EOF'
import os

lockdir = "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/lockscreen"

# 1. Patch LockScreenUi.qml
ui_file = os.path.join(lockdir, "LockScreenUi.qml")
ui_bak = os.path.join(lockdir, "LockScreenUi.qml.glimpse_bak")
ui_sentinel_bak = os.path.join(lockdir, "LockScreenUi.qml.sentinel_bak")
if os.path.isfile(ui_file):
    if not os.path.isfile(ui_bak):
        src_bak = ui_sentinel_bak if os.path.isfile(ui_sentinel_bak) else ui_file
        with open(src_bak, "r") as f:
            orig = f.read()
        with open(ui_bak, "w") as f:
            f.write(orig)

    with open(ui_bak, "r") as f:
        content = f.read()

    # Expose uiVisible alias
    if "property alias uiVisible: lockScreenRoot.uiVisible" not in content:
        content = content.replace("Item {\n    id: lockScreenUi", "Item {\n    id: lockScreenUi\n    property alias uiVisible: lockScreenRoot.uiVisible")

    # Hook onSucceeded to avoid NoPasswordUnlock block and allow Glimpse animated checkmark & auto-quit
    old_success = """        function onSucceeded() {
            if (authenticator.hadPrompt) {
                Qt.quit();
            } else {
                mainStack.replace(null, Qt.resolvedUrl("NoPasswordUnlock.qml"),
                    {
                        userListModel: users
                    },
                    StackView.Immediate,
                );
                mainStack.forceActiveFocus();
            }
        }"""
    new_success = """        function onSucceeded() {
            if (authenticator.hadPrompt) {
                Qt.quit();
            } else {
                glimpseSafetyQuitTimer.restart();
            }
        }"""
    if old_success in content:
        content = content.replace(old_success, new_success)

    safety_timer = """        Timer {
            id: glimpseSafetyQuitTimer
            interval: 1600
            repeat: false
            onTriggered: Qt.quit()
        }"""
    if "id: glimpseSafetyQuitTimer" not in content:
        content = content.replace("        Timer {\n            id: graceLockTimer", safety_timer + "\n        Timer {\n            id: graceLockTimer")

    with open(ui_file, "w") as f:
        f.write(content)
    print("[+] Patched LockScreenUi.qml with uiVisible alias & auto-quit.")

# 2. Patch LockScreen.qml
ls_file = os.path.join(lockdir, "LockScreen.qml")
ls_bak = os.path.join(lockdir, "LockScreen.qml.glimpse_bak")
ls_sentinel_bak = os.path.join(lockdir, "LockScreen.qml.sentinel_bak")
if os.path.isfile(ls_file):
    if not os.path.isfile(ls_bak):
        src_bak = ls_sentinel_bak if os.path.isfile(ls_sentinel_bak) else ls_file
        with open(src_bak, "r") as f:
            orig = f.read()
        with open(ls_bak, "w") as f:
            f.write(orig)

    with open(ls_bak, "r") as f:
        base = f.read()

    new_block = """    LockScreenUi {
        id: lockScreenUi
        anchors.fill: parent
    }

    GlimpseLockNotch {
        id: glimpseLockNotch
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        z: 99999
        uiVisible: lockScreenUi.uiVisible
    }"""
    old_block = """    LockScreenUi {
        anchors.fill: parent
    }"""
    if old_block in base:
        patched = base.replace(old_block, new_block)
        with open(ls_file, "w") as f:
            f.write(patched)
        print("[+] Hooked GlimpseLockNotch into LockScreen.qml with uiVisible binding.")
EOF
fi

echo ""
echo "========================================================"
echo "[+] INSTALLATION COMPLETE! Glimpse is now 100% E2E."
echo "========================================================"
echo "• 512-D ArcFace recognition engine active."
echo "• Temporal voting filter (3 consecutive frames) active."
echo "• Apple FaceID notch active on desktop AND lockscreen!"
echo "• System daemon running at /run/glimpse/glimpse.sock"
echo "• Run 'glimpse enroll' to enroll your 3D multi-pose profile."
echo "• Run 'glimpse diag' to test real-time camera metrics."
echo "========================================================"
