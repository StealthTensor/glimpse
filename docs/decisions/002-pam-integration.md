# ADR 002 --- PAM Integration

Decision: keep PAM as the system authentication boundary.

Reason: PAM already integrates with sudo, login and other authentication
consumers.

Constraint: Never make the PAM module perform heavy computer-vision
inference itself.
