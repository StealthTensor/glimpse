# KDE Integration

Target environment: KDE Plasma 6.4.5 on Wayland.

Integration should use existing system authentication paths rather than
replacing the lock screen.

Initial priority: 1. PAM compatibility. 2. Screen unlock through the
existing PAM path. 3. Optional user-session UI for enrollment/status.

The GUI must not be the trusted authentication boundary.
