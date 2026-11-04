/* Demonstrate stale origins without thread reuse or concurrent lookups. */
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/stat.h>
#include <unistd.h>
extern ssize_t fsgetpath(char *, size_t, fsid_t *, uint64_t);
static char paths[2][MAXPATHLEN];
static int target, use_open;
static int touch(int index) {
    struct stat st;
    if (!use_open) return stat(paths[index], &st);
    int fd = open(paths[index], O_RDONLY);
    return fd < 0 ? -1 : close(fd);
}
static void *worker(void *unused) {
    (void)unused;
    return touch(target) ? (void *)1 : NULL;
}
static int which(const char *path) {
    return !strcmp(path, paths[0]) ? 0 : !strcmp(path, paths[1]) ? 1 : 2;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    for (int i = 0; i < 2; ++i) if (!realpath(argv[i+1], paths[i])) return 2;
    int held = open(paths[1], O_RDONLY);
    struct stat st;
    struct statfs fs;
    if (held < 0 || fstat(held, &st) || fstatfs(held, &fs)) return 2;
    printf("{\"event\":\"identity\",\"filesystem\":\"%s\",\"inode\":%llu,\"nlink\":%u}\n",
        fs.f_fstypename, (unsigned long long)st.st_ino, (unsigned int)st.st_nlink);
    const char *modes[] = {"self", "thread", "thread-self", "thread-bounce"};
    for (int trial = 0; trial < 100; ++trial)
        for (target = 0; target < 2; ++target)
            for (use_open = 0; use_open < 2; ++use_open)
                for (int mode = 0; mode < 4; ++mode) {
                    if (touch(target) || touch(1-target)) return 2;
                    if (!mode) {
                        if (touch(target)) return 2;
                    } else {
                        pthread_t thread;
                        void *result;
                        if (pthread_create(&thread, NULL, worker, NULL) || pthread_join(thread, &result) || result) return 2;
                        if (mode == 2 && touch(target)) return 2;
                        if (mode == 3 && (touch(1-target) || touch(target))) return 2;
                    }
                    char by_fd[MAXPATHLEN], by_id[MAXPATHLEN];
                    if (fcntl(held, F_GETPATH, by_fd) || fsgetpath(by_id, sizeof(by_id), &fs.f_fsid, st.st_ino) < 0) return 2;
                    printf("{\"event\":\"stale\",\"trial\":%d,\"mode\":\"%s\",\"operation\":\"%s\",\"target\":%d,\"parent_fd\":%d,\"parent_id\":%d}\n",
                        trial, modes[mode], use_open ? "open" : "stat", target, which(by_fd), which(by_id));
                }
    close(held);
    return 0;
}
