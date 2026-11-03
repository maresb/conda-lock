/* Compare descriptor- and inode-based lookup for an existing pair of hardlinks.
 * Usage: path_identity CACHE_PATH ENV_PATH [--hold-env-fd]
 * This probes APIs; it does not execute the binary or prove dyld uses that path.
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/stat.h>
#include <unistd.h>

/* Exported Darwin API; some Command Line Tools SDKs omit its public header. */
extern ssize_t fsgetpath(char *, size_t, fsid_t *, uint64_t);

int main(int argc, char **argv) {
    if (argc != 3 && (argc != 4 || strcmp(argv[3], "--hold-env-fd"))) return 2;
    char expected[2][MAXPATHLEN];
    struct stat stats[2];
    for (int i = 0; i < 2; ++i) {
        if (!realpath(argv[i + 1], expected[i]) || stat(argv[i + 1], &stats[i])) {
            perror("input"); return 1;
        }
    }
    if (stats[0].st_dev != stats[1].st_dev || stats[0].st_ino != stats[1].st_ino) {
        fprintf(stderr, "Inputs must be hardlinks to the same inode\n"); return 1;
    }
    unsigned int counts[2][2][3] = {{{0}}};
    int held_fd = argc == 4 ? open(argv[2], O_RDONLY) : -1;
    if (argc == 4 && held_fd < 0) { perror("open env"); return 1; }
    for (int i = 0; i < 1000; ++i) {
        int last = i % 2;
        int fd = -1;
        for (int j = 0; j < 2; ++j) {
            if (fd >= 0) close(fd);
            fd = open(argv[1 + ((last + 1 + j) % 2)], O_RDONLY);
            if (fd < 0) { perror("open"); return 1; }
        }
        struct statfs fs;
        if (fstatfs(fd, &fs)) { perror("fstatfs"); return 1; }
        char paths[2][MAXPATHLEN];
        if (fcntl(held_fd < 0 ? fd : held_fd, F_GETPATH, paths[0]) ||
            fsgetpath(paths[1], sizeof(paths[1]), &fs.f_fsid, stats[0].st_ino) < 0) {
            perror("path lookup"); return 1;
        }
        close(fd);
        for (int api = 0; api < 2; ++api) {
            int result = !strcmp(paths[api], expected[0]) ? 0 :
                         !strcmp(paths[api], expected[1]) ? 1 : 2;
            ++counts[last][api][result];
            if (i < 4) printf("sample last=%s api=%s path=%s\n", last ? "env" : "cache",
                              api ? "fsgetpath" : "F_GETPATH", paths[api]);
        }
    }
    if (held_fd >= 0) close(held_fd);
    for (int last = 0; last < 2; ++last)
        for (int api = 0; api < 2; ++api)
            printf("last=%s api=%s cache=%u env=%u other=%u\n", last ? "env" : "cache",
                   api ? "fsgetpath" : "F_GETPATH", counts[last][api][0],
                   counts[last][api][1], counts[last][api][2]);
    return 0;
}
