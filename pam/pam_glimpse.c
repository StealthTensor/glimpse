/*
 * pam_glimpse: Thin PAM Adapter for Glimpse Facial Authentication
 * Communicates with glimpsed daemon via Unix domain socket.
 * Fail-open design: falls back cleanly to standard Linux password authentication.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>

#if __has_include(<security/pam_modules.h>)
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#else
/* Standalone Linux PAM ABI definitions */
#define PAM_SUCCESS 0
#define PAM_AUTH_ERR 7
#define PAM_AUTHINFO_UNAVAIL 9
#define PAM_USER_UNKNOWN 10
#define PAM_IGNORE 25
#define PAM_SERVICE 1

#define PAM_EXTERN __attribute__((visibility("default")))

typedef struct pam_handle pam_handle_t;

extern int pam_get_user(pam_handle_t *pamh, const char **user, const char *prompt);
extern int pam_get_item(const pam_handle_t *pamh, int item_type, const void **item);
#endif

#define DEFAULT_SOCKET_PATH "/run/glimpse/glimpse.sock"
#define FALLBACK_USER_SOCKET "/home/%s/.local/share/glimpse/glimpse.sock"
#define TIMEOUT_SEC 3

static int connect_daemon(const char *username) {
    int sock = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sock < 0) {
        return -1;
    }

    struct timeval tv;
    tv.tv_sec = TIMEOUT_SEC;
    tv.tv_usec = 0;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof tv);
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof tv);

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;

    // Try system root socket first
    strncpy(addr.sun_path, DEFAULT_SOCKET_PATH, sizeof(addr.sun_path) - 1);
    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
        return sock;
    }

    // Try user local socket if running in user context
    if (username != NULL) {
        snprintf(addr.sun_path, sizeof(addr.sun_path), FALLBACK_USER_SOCKET, username);
        if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
            return sock;
        }
    }

    close(sock);
    return -1;
}

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)flags;
    (void)argc;
    (void)argv;

    const char *username = NULL;
    int retval = pam_get_user(pamh, &username, NULL);
    if (retval != PAM_SUCCESS || username == NULL) {
        return PAM_USER_UNKNOWN;
    }

    const char *service = "pam";
    const void *svc_item = NULL;
    if (pam_get_item(pamh, PAM_SERVICE, &svc_item) == PAM_SUCCESS && svc_item != NULL) {
        service = (const char *)svc_item;
    }

    // Connect to daemon
    int sock = connect_daemon(username);
    if (sock < 0) {
        // Daemon not running or camera inaccessible - fail open to password
        return PAM_AUTHINFO_UNAVAIL;
    }

    // Format JSON request with dynamic PAM service
    char req[512];
    snprintf(req, sizeof(req), "{\"action\": \"authenticate\", \"username\": \"%s\", \"timeout\": 2.5, \"service\": \"%s\"}\n", username, service);

    ssize_t sent = write(sock, req, strlen(req));
    if (sent <= 0) {
        close(sock);
        return PAM_AUTHINFO_UNAVAIL;
    }

    // Read response
    char resp[1024];
    memset(resp, 0, sizeof(resp));
    ssize_t n = read(sock, resp, sizeof(resp) - 1);
    close(sock);

    if (n <= 0) {
        return PAM_AUTH_ERR;
    }

    // Check for success in response JSON
    if (strstr(resp, "\"status\": \"success\"") != NULL) {
        return PAM_SUCCESS;
    }

    // Biometric match failed or timed out -> proceed to password fallback
    return PAM_AUTH_ERR;
}

PAM_EXTERN int pam_sm_setcred(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_SUCCESS;
}

PAM_EXTERN int pam_sm_acct_mgmt(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_SUCCESS;
}

PAM_EXTERN int pam_sm_open_session(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_SUCCESS;
}

PAM_EXTERN int pam_sm_close_session(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_SUCCESS;
}

PAM_EXTERN int pam_sm_chauthtok(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_SUCCESS;
}
