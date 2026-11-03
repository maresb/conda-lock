/* Exercise the cache operations observed in the GitHub runner trace. */
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/attr.h>
#include <sys/stat.h>
#include <unistd.h>

static volatile sig_atomic_t stopped;
static void stop(int sig) { (void)sig; stopped = 1; }

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    signal(SIGTERM, stop);
    unsigned long count = 0;
    while (!stopped) {
        if (!strcmp(argv[1], "stat")) {
            struct stat st;
            if (stat(argv[2], &st)) { perror("stat"); return 1; }
        } else if (!strcmp(argv[1], "getattrlist")) {
            struct attrlist attrs = {0};
            attrs.bitmapcount = ATTR_BIT_MAP_COUNT;
            attrs.commonattr = ATTR_CMN_NAME | ATTR_CMN_OBJTYPE | ATTR_CMN_FILEID;
            char buffer[4096];
            if (getattrlist(argv[2], &attrs, buffer, sizeof(buffer), 0)) {
                perror("getattrlist"); return 1;
            }
        } else if (!strcmp(argv[1], "open") || !strcmp(argv[1], "event")) {
            int flags = !strcmp(argv[1], "event") ? O_EVTONLY : O_RDONLY;
            int fd = open(argv[2], flags);
            if (fd < 0) { perror("open"); return 1; }
            close(fd);
        } else return 2;
        if (++count == 1) { puts("ready"); fflush(stdout); }
        usleep(50);
    }
    printf("%lu\n", count);
    return 0;
}
