# Failure Modes

  Failure             Face result    Recovery
  ------------------- -------------- ---------------------
  Camera missing      unavailable    password
  Camera busy         unavailable    password
  Model unavailable   unavailable    password
  GPU unavailable     CPU/fallback   continue
  Daemon down         unavailable    password
  Liveness fails      reject         password
  Face mismatch       reject         password
  PAM misconfigured   system risk    documented rollback

Authentication convenience must never become an account lockout
mechanism.
