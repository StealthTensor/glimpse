# Daemon

`glimpsed` provides controlled authentication services.

Responsibilities: - camera lifecycle; - recognition backend; -
liveness; - template access; - policy evaluation; - request
authentication; - timeout/cancellation; - audit logging.

The daemon must not expose a network listener.

Authentication requests should be short-lived and bound to the
requesting user/session where practical.
