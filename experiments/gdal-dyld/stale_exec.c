/* Set a stale per-thread hardlink origin, then execute with no concurrent reader. */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
extern ssize_t fsgetpath(char *, size_t, fsid_t *, uint64_t);
static const char *installed;
static int use_open;
static int touch(const char *path) {
    struct stat st;
    if (!use_open) return stat(path, &st);
    int fd = open(path, O_RDONLY);
    return fd < 0 ? -1 : close(fd);
}
static void *worker(void *unused) {
    (void)unused;
    return touch(installed) ? (void *)1 : NULL;
}
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    const char *mode = argv[1], *cached = argv[2], *method = argv[4];
    installed = argv[3]; use_open = !strcmp(argv[5], "open");
    int fd = open(installed, O_RDONLY);
    struct stat st;
    struct statfs fs;
    if (fd < 0 || fstat(fd, &st) || fstatfs(fd, &fs)) return 2;
    /* Ensure main has visited both aliases, ending on cache. */
    if (touch(installed) || touch(cached)) return 2;
    if (!strcmp(mode, "self")) {
        if (touch(installed)) return 2;
    } else {
        pthread_t thread;
        void *result;
        if (pthread_create(&thread, NULL, worker, NULL) || pthread_join(thread, &result) || result) return 2;
        if (!strcmp(mode, "thread-self") && touch(installed)) return 2;
        if (!strcmp(mode, "thread-bounce") && (touch(cached) || touch(installed))) return 2;
    }
    /* No F_GETPATH/fsgetpath here: those observations can change the next lookup. */
    if (!strcmp(method, "probe")) {
        char path[MAXPATHLEN];
        if (fsgetpath(path, sizeof(path), &fs.f_fsid, st.st_ino) < 0) return 2;
        printf("resolved=%s\n", path);
        return 0;
    }
    close(fd);
    char *args[] = {argv[3], "--version", NULL};
    if (!strcmp(method, "exec")) {
        execve(installed, args, environ);
        perror("execve"); return 2;
    }
    pid_t child;
    int error = posix_spawn(&child, installed, NULL, NULL, args, environ);
    if (error) { errno = error; perror("posix_spawn"); return 2; }
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 2;
    return WIFSIGNALED(status) ? 128 + WTERMSIG(status) : WEXITSTATUS(status);
}
