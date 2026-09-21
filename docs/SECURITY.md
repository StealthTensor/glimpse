# Security

Rules: - Never store the user's Linux password. - Never transmit
biometric data over the network. - Prefer Unix-domain IPC. - Restrict
daemon and template permissions. - Do not expose authentication
endpoints on TCP. - Keep PAM module minimal. - Keep password fallback
enabled. - Do not automatically modify PAM configuration. - Provide a
tested rollback path. - Log authentication events without storing camera
frames or embeddings in logs.

Biometric templates are sensitive data and must be protected
accordingly.
