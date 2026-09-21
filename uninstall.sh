#!/usr/bin/env bash
# Glimpse Clean Uninstaller
set -e

echo "========================================================"
echo "    Glimpse: Uninstaller                              "
echo "========================================================"

echo "[*] Stopping system services..."
sudo systemctl stop glimpsed.service 2>/dev/null || true
sudo systemctl disable glimpsed.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/glimpsed.service
sudo systemctl daemon-reload

echo "[*] Stopping user services..."
systemctl --user stop glimpsed glimpse-ui 2>/dev/null || true
systemctl --user disable glimpsed glimpse-ui 2>/dev/null || true
rm -f ~/.config/systemd/user/glimpsed.service ~/.config/systemd/user/glimpse-ui.service
systemctl --user daemon-reload 2>/dev/null || true

echo "[*] Removing autostart entry..."
rm -f ~/.config/autostart/glimpse-ui.desktop

echo "[*] Restoring PAM configurations..."
if [ -f /etc/pam.d/sudo.glimpse_bak ]; then
    sudo mv /etc/pam.d/sudo.glimpse_bak /etc/pam.d/sudo
    echo "[+] Restored /etc/pam.d/sudo from backup."
else
    sudo sed -i '/pam_glimpse.so/d' /etc/pam.d/sudo 2>/dev/null || true
fi

if [ -f /etc/pam.d/sddm.glimpse_bak ]; then
    sudo mv /etc/pam.d/sddm.glimpse_bak /etc/pam.d/sddm
    echo "[+] Restored /etc/pam.d/sddm from backup."
else
    sudo sed -i '/pam_glimpse.so/d' /etc/pam.d/sddm 2>/dev/null || true
fi

if [ -f /etc/pam.d/kde ]; then
    sudo rm -f /etc/pam.d/kde /etc/pam.d/kscreenlocker
    echo "[+] Removed /etc/pam.d/kde and /etc/pam.d/kscreenlocker."
fi

if [ -f /etc/pam.d/polkit-1.glimpse_bak ]; then
    sudo mv /etc/pam.d/polkit-1.glimpse_bak /etc/pam.d/polkit-1
    echo "[+] Restored /etc/pam.d/polkit-1 from backup."
elif [ -f /etc/pam.d/polkit-1 ]; then
    sudo rm -f /etc/pam.d/polkit-1
    echo "[+] Removed /etc/pam.d/polkit-1."
fi

rm -f ~/.local/share/kio/servicemenus/glimpse_folders.desktop 2>/dev/null || true

echo "[*] Removing system binaries and PAM modules..."
sudo rm -f /lib/security/pam_glimpse.so /usr/lib/x86_64-linux-gnu/security/pam_glimpse.so
sudo rm -f /usr/local/bin/glimpse /usr/local/bin/glimpse-ui /usr/local/bin/glimpse-diag

echo "[*] Restoring KDE Lockscreen QML..."
LOCKSCREEN_DIR="/usr/share/plasma/shells/org.kde.plasma.desktop/contents/lockscreen"
if [ -f "${LOCKSCREEN_DIR}/LockScreen.qml.glimpse_bak" ]; then
    sudo mv "${LOCKSCREEN_DIR}/LockScreen.qml.glimpse_bak" "${LOCKSCREEN_DIR}/LockScreen.qml"
    echo "[+] Restored original KDE LockScreen.qml."
fi
if [ -f "${LOCKSCREEN_DIR}/LockScreenUi.qml.glimpse_bak" ]; then
    sudo mv "${LOCKSCREEN_DIR}/LockScreenUi.qml.glimpse_bak" "${LOCKSCREEN_DIR}/LockScreenUi.qml"
    echo "[+] Restored original KDE LockScreenUi.qml."
fi
sudo rm -f "${LOCKSCREEN_DIR}/GlimpseLockNotch.qml"

echo "[+] Uninstalled cleanly. Standard password authentication restored."
