# ADR 005 --- Liveness

Decision: liveness is a separate stage before authentication.

Consequence: A face match without successful liveness must not
authenticate.

RGB liveness does not eliminate all presentation attacks.
