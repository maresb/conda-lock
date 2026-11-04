/* Probe pathname selection without executing the hardlinked file. */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/attr.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

extern ssize_t fsgetpath(char *, size_t, fsid_t *, uint64_t);

static char paths[2][MAXPATHLEN];
static int held[2], dirs[2];
static fsid_t fsid;
static uint64_t inode;
static int operation, target, operation_error;
static char actor_path[MAXPATHLEN];

static void *lookup(void *unused) {
    (void)unused;
    struct stat st;
    int fd, rc = 0;
    char buffer[MAXPATHLEN];
    struct attrlist attr = {.bitmapcount = ATTR_BIT_MAP_COUNT, .commonattr = ATTR_CMN_FILEID};
    switch (operation) {
        case 0: break;
        case 1:
            fd = open(paths[target], O_RDONLY);
            rc = fd < 0 ? -1 : close(fd); break;
        case 2: rc = stat(paths[target], &st); break;
        case 3: rc = fstat(held[target], &st); break;
        case 4: rc = access(paths[target], F_OK); break;
        case 5: rc = getattrlist(paths[target], &attr, buffer, sizeof(buffer), 0); break;
        case 6:
            fd = openat(dirs[target], "file", O_RDONLY);
            rc = fd < 0 ? -1 : close(fd); break;
        case 7: rc = fstatat(dirs[target], "file", &st, 0); break;
        case 8: rc = fcntl(held[target], F_GETPATH, buffer); break;
        default: rc = -1; errno = EINVAL;
    }
    operation_error = rc < 0 ? errno : 0;
    if (fsgetpath(actor_path, sizeof(actor_path), &fsid, inode) < 0) {
        perror("actor fsgetpath"); exit(2);
    }
    return NULL;
}

static int which(const char *path) {
    return !strcmp(path, paths[0]) ? 0 : !strcmp(path, paths[1]) ? 1 : 2;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    for (int i = 0; i < 2; ++i) {
        if (!realpath(argv[i + 1], paths[i])) { perror("realpath"); return 2; }
        held[i] = open(paths[i], O_RDONLY);
        char parent[MAXPATHLEN];
        strlcpy(parent, paths[i], sizeof(parent));
        *strrchr(parent, '/') = 0;
        dirs[i] = open(parent, O_RDONLY);
        if (held[i] < 0 || dirs[i] < 0) { perror("open"); return 2; }
    }
    struct stat st[2];
    struct statfs fs;
    if (fstat(held[0], &st[0]) || fstat(held[1], &st[1]) || fstatfs(held[0], &fs)) return 2;
    if (st[0].st_ino != st[1].st_ino || st[0].st_dev != st[1].st_dev) return 2;
    inode = st[0].st_ino; fsid = fs.f_fsid;
    printf("{\"event\":\"identity\",\"filesystem\":\"%s\",\"inode\":%llu,\"nlink\":%u}\n",
        fs.f_fstypename, (unsigned long long)inode, st[0].st_nlink);
    const char *names[] = {"none", "open", "stat", "fstat", "access", "getattrlist", "openat", "fstatat", "F_GETPATH"};
    const char *actors[] = {"self", "thread", "process"};
    for (int trial = 0; trial < 100; ++trial) {
        for (int actor = 0; actor < 3; ++actor) {
            for (operation = 0; operation < 9; ++operation) {
                for (target = 0; target < 2; ++target) {
                    /* Establish the other alias immediately before each operation. */
                    int fd = open(paths[1 - target], O_RDONLY);
                    if (fd < 0 || close(fd)) return 2;
                    char before[MAXPATHLEN], by_fd[MAXPATHLEN], by_id[MAXPATHLEN];
                    if (fsgetpath(before, sizeof(before), &fsid, inode) < 0) return 2;
                    if (actor == 0) lookup(NULL);
                    else if (actor == 1) {
                        pthread_t thread;
                        if (pthread_create(&thread, NULL, lookup, NULL) || pthread_join(thread, NULL)) return 2;
                    } else {
                        int pipefd[2];
                        if (pipe(pipefd)) return 2;
                        fflush(stdout);
                        pid_t child = fork();
                        if (child < 0) return 2;
                        if (!child) {
                            close(pipefd[0]); lookup(NULL);
                            if (write(pipefd[1], actor_path, sizeof(actor_path)) != sizeof(actor_path)) _exit(2);
                            _exit(operation_error ? 2 : 0);
                        }
                        close(pipefd[1]);
                        size_t got = 0;
                        while (got < sizeof(actor_path)) {
                            ssize_t n = read(pipefd[0], actor_path + got, sizeof(actor_path) - got);
                            if (n <= 0) return 2;
                            got += n;
                        }
                        close(pipefd[0]);
                        int status;
                        if (waitpid(child, &status, 0) < 0 || !WIFEXITED(status) || WEXITSTATUS(status)) return 2;
                    }
                    if (operation_error || fcntl(held[1], F_GETPATH, by_fd) ||
                        fsgetpath(by_id, sizeof(by_id), &fsid, inode) < 0) return 2;
                    printf("{\"event\":\"lookup\",\"trial\":%d,\"actor\":\"%s\",\"operation\":\"%s\",\"target\":%d,\"before\":%d,\"actor_path\":%d,\"parent_fd\":%d,\"parent_id\":%d}\n",
                        trial, actors[actor], names[operation], target, which(before), which(actor_path), which(by_fd), which(by_id));
                }
            }
        }
    }
    return 0;
}
