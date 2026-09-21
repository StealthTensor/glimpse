/*
 * Test harness for pam_glimpse.so
 * Directly invokes pam_sm_authenticate with a simulated PAM environment.
 */

#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>
#include <assert.h>

#define PAM_SUCCESS 0
#define PAM_AUTH_ERR 7
#define PAM_AUTHINFO_UNAVAIL 9
#define PAM_USER_UNKNOWN 10

typedef struct pam_handle pam_handle_t;
typedef int (*pam_sm_auth_fn)(pam_handle_t *, int, int, const char **);

// Mock implementation of pam_get_user
static const char *g_mock_user = "stealthtensor";
int pam_get_user(pam_handle_t *pamh, const char **user, const char *prompt) {
    (void)pamh;
    (void)prompt;
    *user = g_mock_user;
    return PAM_SUCCESS;
}

int main(int argc, char **argv) {
    const char *so_path = "pam/pam_glimpse.so";
    if (argc > 1) {
        g_mock_user = argv[1];
    }

    printf("[*] Testing pam_glimpse.so with simulated user: '%s'...\n", g_mock_user);

    void *handle = dlopen(so_path, RTLD_NOW);
    if (!handle) {
        fprintf(stderr, "[!] dlopen failed: %s\n", dlerror());
        return 1;
    }

    pam_sm_auth_fn auth = (pam_sm_auth_fn)dlsym(handle, "pam_sm_authenticate");
    if (!auth) {
        fprintf(stderr, "[!] dlsym failed: %s\n", dlerror());
        dlclose(handle);
        return 1;
    }

    int ret = auth(NULL, 0, 0, NULL);
    printf("[+] pam_sm_authenticate returned code: %d\n", ret);

    if (ret == PAM_SUCCESS) {
        printf("[+] SUCCESS: PAM module successfully authenticated user via glimpsed!\n");
    } else if (ret == PAM_AUTH_ERR) {
        printf("[-] AUTH_ERR: User did not match or auth failed (fallback to password).\n");
    } else if (ret == PAM_AUTHINFO_UNAVAIL) {
        printf("[!] AUTHINFO_UNAVAIL: Daemon unreachable (fallback to password).\n");
    } else {
        printf("[?] Other PAM return code: %d\n", ret);
    }

    dlclose(handle);
    return (ret == PAM_SUCCESS ? 0 : 2);
}
