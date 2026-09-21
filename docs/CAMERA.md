# Camera

Default device: `/dev/video0`.

Preferred capture mode: - MJPEG - 1280x720 - 30 FPS

Fallback: - YUYV - 640x480 or 640x360

Never use `/dev/video2` for authentication.

Camera access must: - detect device availability; - release the device
after authentication; - fail closed for the face method but allow
password fallback; - avoid leaving a persistent camera stream open
unnecessarily.
