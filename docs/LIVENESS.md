# Liveness

The built-in camera is RGB-only based on current inspection.

Therefore: - liveness is required for face authentication; - RGB
liveness reduces simple spoofing but does not provide IR/depth
assurance; - printed photos and screen attacks remain part of the threat
model; - Glimpse must not advertise RGB authentication as equivalent to
Windows Hello IR/depth authentication.

For higher assurance, support future IR/depth or hardware-backed
credentials.
