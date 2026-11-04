/* Create the stale state once, then spawn the hardlinked executable several
 * times from the same long-lived process: no intermediate process or thread
 * can take the freed identity between launches.
 * respawn CACHED INSTALLED REPEATS */
#include <errno.h>
#include <pthread.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
static const char *cached;
static void *worker(void *unused) {
    (void)unused;
    struct stat st;
    if (stat(cached, &st)) abort();
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    cached = argv[1];
    const char *installed = argv[2];
    int repeats = atoi(argv[3]);
    if (repeats < 1 || repeats > 10) return 2;
    pthread_t thread;
    if (pthread_create(&thread, NULL, worker, NULL) || pthread_join(thread, NULL)) return 2;
    struct stat st;
    if (stat(installed, &st)) return 2;
    char *args[] = {argv[2], NULL};
    for (int i = 0; i < repeats; ++i) {
        pid_t child;
        int error = posix_spawn(&child, installed, NULL, NULL, args, environ);
        if (error) { errno = error; perror("posix_spawn"); return 2; }
        int status;
        while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 2;
        if (!WIFEXITED(status) || WEXITSTATUS(status)) return 3;
        printf("launch=%d\n", i);
        fflush(stdout);
    }
    return 0;
}
