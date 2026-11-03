/* Perform one pathname lookup after exec has started, before dyld runs. */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static int touch(const char *path, int use_stat) {
    if (use_stat) {
        struct stat st;
        return stat(path, &st);
    }
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    return close(fd);
}

int main(int argc, char **argv) {
    if (argc != 4) return 2;
    const char *operation = argv[1], *cached = argv[2], *installed = argv[3];
    posix_spawnattr_t attr;
    int err = posix_spawnattr_init(&attr);
    if (err) return 2;
    err = posix_spawnattr_setflags(&attr, POSIX_SPAWN_START_SUSPENDED);
    if (err) return 2;
    char *args[] = {argv[3], "--version", NULL};
    pid_t pid;
    err = posix_spawn(&pid, installed, NULL, &attr, args, environ);
    posix_spawnattr_destroy(&attr);
    if (err) { errno = err; perror("posix_spawn"); return 2; }
    printf("suspended_child_pid=%d\n", pid); fflush(stdout);
    int lookup_error = 0;
    if (strcmp(operation, "none")) {
        lookup_error = touch(cached, !strcmp(operation, "stat-cache"));
        if (!lookup_error && !strcmp(operation, "open-cache-open-env"))
            lookup_error = touch(installed, 0);
        if (!lookup_error && !strcmp(operation, "open-cache-stat-env"))
            lookup_error = touch(installed, 1);
    }
    if (lookup_error) {
        perror("lookup");
        kill(pid, SIGKILL);
    } else if (kill(pid, SIGCONT)) {
        perror("SIGCONT"); kill(pid, SIGKILL); lookup_error = 1;
    }
    int status;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) { perror("waitpid"); return 2; }
    }
    if (lookup_error) return 2;
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return WEXITSTATUS(status);
}
