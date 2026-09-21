# Hardware

Target: - OS: Kubuntu 25.10, x86_64 - Kernel: 6.17 - DE: KDE Plasma
6.4.5 - Session: Wayland - CPU: Intel Core i5-13500H - GPU: NVIDIA RTX
4050 Mobile + Intel Iris Xe - RAM: 16 GB - Camera: HP Wide Vision HD
Camera, USB ID `30c9:0069`

V4L2: - `/dev/video0`: actual camera capture, UVC, MJPEG/YUYV, up to
1280x720 @ 30 FPS. - `/dev/video1`: UVC metadata capture (`UVCH`), not a
second image stream. - `/dev/video2`: OBS virtual camera; not used by
Glimpse.

No separate IR camera endpoint is currently exposed. Glimpse therefore
treats the built-in camera as RGB-only unless future hardware inspection
proves otherwise.
