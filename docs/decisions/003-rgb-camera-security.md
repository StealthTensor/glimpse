# ADR 003 --- RGB Security Model

Decision: classify the built-in camera as convenience biometric
authentication.

Reason: Current V4L2/USB inspection exposes an RGB UVC camera, not a
dedicated IR/depth device.

Consequence: Liveness is mandatory and security claims remain limited.
