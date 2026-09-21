# sudo

Initial target: face authentication as an alternative to the existing
password path.

Required behavior: - face success → authentication success; - face
failure/timeout → password remains available; - camera unavailable →
password remains available; - daemon unavailable → password remains
available.

Do not cache passwords or create a password-equivalent local secret.
