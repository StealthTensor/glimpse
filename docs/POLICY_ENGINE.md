# Policy Engine

Authentication is policy-driven.

Example:

``` yaml
sudo:
  methods: [face, password]
  liveness: required

unlock:
  methods: [face, password]
  liveness: required

high_risk:
  methods: [password]
```

Policy evaluation must be deterministic, auditable and deny-by-default
for unknown resources.

Policy must never silently remove the password recovery path.
