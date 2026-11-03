/* Repeatedly access only the supplied experiment files until SIGTERM. */
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopped = 0;
static void stop(int unused) { (void)unused; stopped = 1; }

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    signal(SIGTERM, stop);
    struct timespec pause = {0, 50000};
    puts("ready"); fflush(stdout);
    while (!stopped) {
        for (int i = 1; i < argc; ++i) {
            int fd = open(argv[i], O_RDONLY);
            if (fd < 0) { perror(argv[i]); return 1; }
            close(fd);
        }
        nanosleep(&pause, NULL);
    }
    return 0;
}
