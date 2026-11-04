/* Model installer workers exiting before a new executable thread is created. */
#include <errno.h>
#include <pthread.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
static const char *target;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cond = PTHREAD_COND_INITIALIZER;
static int ready, release_workers;
static void release(pthread_t *threads, int count) {
    pthread_mutex_lock(&mutex);
    release_workers = 1;
    pthread_cond_broadcast(&cond);
    pthread_mutex_unlock(&mutex);
    for (int i = 0; i < count; ++i) if (pthread_join(threads[i], NULL)) abort();
}
static void *worker(void *unused) {
    (void)unused;
    struct stat st;
    if (stat(target, &st)) abort();
    pthread_mutex_lock(&mutex);
    ++ready;
    pthread_cond_broadcast(&cond);
    while (!release_workers) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    int count = atoi(argv[5]);
    if (count < 0 || count > 128) return 2;
    int keep_alive = strstr(argv[1], "alive") != NULL;
    target = !strncmp(argv[1], "cache", 5) ? argv[2] : argv[3];
    pthread_t threads[128];
    for (int i = 0; i < count; ++i) {
        if (pthread_create(&threads[i], NULL, worker, NULL)) return 2;
        pthread_mutex_lock(&mutex);
        while (ready != i + 1) pthread_cond_wait(&cond, &mutex);
        pthread_mutex_unlock(&mutex);
    }
    /* Correct global path before releasing the workers. No later cache lookup. */
    struct stat st;
    if (stat(argv[3], &st)) return 2;
    if (!keep_alive) release(threads, count);
    uint64_t tid;
    if (pthread_threadid_np(NULL, &tid)) return 2;
    printf("primed_threads=%d caller_thread=%llu\n", count, (unsigned long long)tid);
    fflush(stdout);
    char *args[] = {argv[3], "--version", NULL};
    if (!strcmp(argv[4], "exec")) {
        execve(argv[3], args, environ);
        perror("execve"); return 2;
    }
    pid_t child;
    int error = posix_spawn(&child, argv[3], NULL, NULL, args, environ);
    if (error) { errno = error; perror("posix_spawn"); return 2; }
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 2;
    if (keep_alive) release(threads, count);
    return WIFSIGNALED(status) ? 128 + WTERMSIG(status) : WEXITSTATUS(status);
}
