/* Spawn a path with no preceding lookup of it and return its exit status. */
#include <errno.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
extern char **environ;
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    char *args[] = {argv[1], NULL};
    pid_t child;
    int error = posix_spawn(&child, argv[1], NULL, NULL, args, environ);
    if (error) { errno = error; perror("posix_spawn"); return 2; }
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 2;
    return WIFSIGNALED(status) ? 128 + WTERMSIG(status) : WEXITSTATUS(status);
}
