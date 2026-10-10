// Launcher for "xBloom Bridge.app". exec keeps this process, so macOS attributes the
// server's Bluetooth use to the app bundle, which can hold the permission.
// REPO_DIR is baked in by build-app.sh.
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(void) {
    char log[1024];
    snprintf(log, sizeof log, "%s/Library/Logs/xbloom-mcp.log", getenv("HOME"));
    freopen(log, "a", stdout);
    freopen(log, "a", stderr);
    execl("/bin/zsh", "zsh", REPO_DIR "/deploy/run-server.sh", (char *)NULL);
    perror("exec");
    return 1;
}
