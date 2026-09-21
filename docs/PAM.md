# PAM

PAM integration is a thin adapter.

Flow:

``` text
PAM application
  ↓
pam_glimpse.so
  ↓
glimpsed
  ↓
camera → liveness → recognition
  ↓
result
```

PAM changes must initially be manual and explicitly confirmed.

Never remove password authentication while developing.

Before enabling PAM: 1. Verify `faceauth verify` independently. 2.
Verify daemon recovery. 3. Verify password authentication. 4. Keep an
existing root shell/TTY available. 5. Make a reversible PAM
configuration backup. 6. Test one service at a time.
