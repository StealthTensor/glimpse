# Testing

Functional: - camera detected; - camera unavailable; - enrollment; -
recognition; - rejection; - multiple enrollment templates; - timeout; -
daemon restart; - GPU unavailable; - malformed IPC; - password fallback.

Security: - unauthorized user cannot read templates; - unauthorized user
cannot access daemon; - camera frames are not persisted; - embeddings
are not logged; - PAM rollback works; - face failure never locks the
account out.

Spoof tests: - printed photo; - phone display; - replayed video; -
different person; - low light; - glasses; - pose changes.
