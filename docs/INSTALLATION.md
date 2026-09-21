# Installation

Development installation must not alter PAM automatically.

Order: 1. Install development dependencies. 2. Detect camera. 3. Install
recognition backend. 4. Run standalone camera test. 5. Enroll. 6. Run
standalone verification. 7. Start daemon. 8. Test IPC. 9. Install PAM
adapter. 10. Configure one PAM service manually. 11. Test password
fallback. 12. Expand to other services.

Howdy may be installed as the first backend if its Kubuntu 25.10
packaging/dependencies are confirmed compatible.
