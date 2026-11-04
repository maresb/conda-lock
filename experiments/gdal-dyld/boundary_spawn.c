/* Observe a suspended process's executable inode around one alias lookup. */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
extern ssize_t fsgetpath(char *, size_t, fsid_t *, uint64_t);
static int held;
static fsid_t fsid;
static uint64_t inode;

static void observe(const char *phase) {
    char fdpath[MAXPATHLEN], idpath[MAXPATHLEN];
    if (fcntl(held, F_GETPATH, fdpath) || fsgetpath(idpath, sizeof(idpath), &fsid, inode) < 0) {
        perror("observe"); exit(2);
    }
    printf("%s_fd=%s\n%s_id=%s\n", phase, fdpath, phase, idpath);
    fflush(stdout);
}

static int touch(const char *path, int use_stat) {
    struct stat st;
    if (use_stat) return stat(path, &st);
    int fd = open(path, O_RDONLY);
    return fd < 0 ? -1 : close(fd);
}

int main(int argc, char **argv) {
    if (argc != 5) return 2;
    const char *op = argv[1], *alias = argv[2], *installed = argv[3];
    unsigned int delay_us = (unsigned int)strtoul(argv[4], NULL, 10);
    held = open(installed, O_RDONLY);
    struct stat st;
    struct statfs fs;
    if (held < 0 || fstat(held, &st) || fstatfs(held, &fs)) return 2;
    inode = st.st_ino; fsid = fs.f_fsid;
    if (!strcmp(op, "pre-stat-alias") && touch(alias, 1)) return 2;
    observe("pre_spawn");
    posix_spawnattr_t attr;
    if (posix_spawnattr_init(&attr) || posix_spawnattr_setflags(&attr, POSIX_SPAWN_START_SUSPENDED)) return 2;
    char *args[] = {argv[3], "--version", NULL};
    pid_t child;
    int error = posix_spawn(&child, installed, NULL, &attr, args, environ);
    posix_spawnattr_destroy(&attr);
    if (error) { errno = error; perror("posix_spawn"); return 2; }
    printf("child_pid=%d\n", child);
    observe("suspended");
    if (!strcmp(op, "stat-alias") || !strncmp(op, "stat-alias-", 11)) {
        if (touch(alias, 1)) error = 1;
    }
    if (!strcmp(op, "stat-env") || !strcmp(op, "stat-alias-stat-env")) {
        if (touch(installed, 1)) error = 1;
    }
    if (!strcmp(op, "stat-alias-open-env") && touch(installed, 0)) error = 1;
    if (!strcmp(op, "stat-alias-fstat-env") && fstat(held, &st)) error = 1;
    observe("after_lookup");
    if (delay_us) usleep(delay_us);
    observe("pre_resume");
    if (error) kill(child, SIGKILL);
    else if (kill(child, SIGCONT)) { kill(child, SIGKILL); error = 1; }
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 2;
    close(held);
    if (error) return 2;
    return WIFSIGNALED(status) ? 128 + WTERMSIG(status) : WEXITSTATUS(status);
}
