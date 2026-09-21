# Architecture

``` text
Camera
  ↓
Capture
  ↓
Face detection / alignment
  ↓
Liveness
  ↓
Embedding
  ↓
Matcher
  ↓
Policy engine
  ↓
Authentication result
  ↓
PAM
  ├─ sudo
  ├─ login
  └─ unlock
```

Components: - `engine`: camera, detection, embedding, liveness,
matching. - `daemon`: privileged/controlled authentication service and
IPC. - `cli`: enrollment, verification, diagnostics and policy
management. - `pam`: thin PAM adapter; never implements recognition
itself. - `policy`: decides which authentication methods are allowed. -
`storage`: protected biometric templates and configuration.

Howdy may be used as an initial PAM/recognition backend. Glimpse must
not depend architecturally on Howdy.
