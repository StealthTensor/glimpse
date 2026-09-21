# ADR 001 --- Howdy vs Custom Engine

Decision: use Howdy as an optional initial backend where compatible.

Reason: - existing PAM integration; - existing enrollment and
verification; - reduced implementation risk.

Constraint: Glimpse remains backend-independent so a native engine can
replace Howdy later.
