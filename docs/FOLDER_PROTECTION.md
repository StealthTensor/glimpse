# Folder Protection

`faceauth protect <resource>` must not pretend to provide encryption by
itself.

Potential implementations: - authorization gate for controlled access; -
encrypted filesystem integration; - per-resource policy; -
application-specific access control.

A future implementation should use an OS-enforced boundary where
confidentiality matters.
