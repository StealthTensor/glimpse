# Threat Model

Protected asset: local user account and authenticated privileged
actions.

Threats: - printed photo spoof; - phone/screen replay; - look-alike
face; - stolen biometric template; - malicious local process; -
compromised camera pipeline; - PAM misconfiguration; - daemon
compromise; - denial of service through camera failure.

Out of scope for RGB V1: - defeating a determined attacker with physical
access; - guaranteeing biometric uniqueness; - replacing hardware-backed
authentication.

Security principle: Face authentication is a convenience factor.
Password recovery remains mandatory.
