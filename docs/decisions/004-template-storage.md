# ADR 004 --- Template Storage

Decision: store protected face embeddings rather than raw images by
default.

Requirements: - restricted permissions; - no world-readable templates; -
no template data in logs; - removal command must securely remove
application references.
