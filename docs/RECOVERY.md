# Recovery

Before enabling PAM, maintain: - an existing root shell; - a working
password; - a tested TTY/recovery route; - a backup of affected PAM
configuration.

Emergency objective:

``` text
disable Glimpse PAM integration
        ↓
restore original PAM configuration
        ↓
reboot/test
```

No installer should make irreversible authentication changes.
