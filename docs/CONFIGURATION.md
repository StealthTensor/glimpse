# Configuration

Configuration should be declarative and separate from biometric
templates.

Example:

``` toml
[engine]
backend = "howdy"
device = "/dev/video0"
width = 1280
height = 720
fps = 30

[authentication]
password_fallback = true
timeout_seconds = 10
liveness_required = true

[daemon]
socket = "/run/glimpse/glimpse.sock"
```

Do not store secrets in configuration files.
