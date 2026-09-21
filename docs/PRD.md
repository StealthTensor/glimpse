# Glimpse --- Product Requirements

## Goal

Provide local facial authentication for Linux actions that normally
require authentication.

## V1

-   Face enrollment and verification.
-   RGB webcam support.
-   Local inference.
-   Liveness detection appropriate to RGB hardware.
-   PAM integration.
-   `sudo` authentication.
-   Screen-unlock integration where supported.
-   Password fallback.
-   CLI diagnostics and recovery.
-   No cloud services or remote biometric processing.

## V2

-   KDE integration.
-   Policy engine.
-   Protected application workflows.
-   Protected resource/folder workflows.
-   Pluggable recognition backends.

## Non-goals

-   Replacing passwords completely.
-   Claiming biometric security equivalent to dedicated IR/depth
    hardware.
-   Storing plaintext passwords.
-   Exposing a network API for authentication.

## Success criteria

-   Enrollment succeeds with the built-in camera.
-   Verification is repeatable under normal lighting.
-   Failed recognition never prevents password fallback.
-   PAM changes are reversible.
-   No biometric template is world-readable.
