/* Exited cache worker, then idle dead or live threads or live environment
 * lookups before launching the hardlinked executable.
 *
 * scrub_exec CACHED INSTALLED exec|spawn STALE DUMMIES HOLDERS EVICTORS [EVICTOR_PATH]
 *   EVICTOR_PATH  what each evictor looks up: INSTALLED by default, "none" for
 *            no lookup, or any other path (an unrelated file).
 *   STALE    1: a worker looks up CACHED and exits before launch; 0: no worker.
 *   DUMMIES  threads created and joined after that exit; no filesystem activity.
 *   HOLDERS  threads created after that exit and kept alive through the launch;
 *            no filesystem activity.
 *   EVICTORS threads kept alive through the launch that each look up INSTALLED
 *            after the stale lookup but before the stale worker exits, so none
 *            of them can reuse its kernel thread object.
 * The main thread looks up INSTALLED after the evictors, before dummies and
 * holders, and before launching, like a shell's PATH search. */
#include <errno.h>
#include <pthread.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cond = PTHREAD_COND_INITIALIZER;
static int ready;
struct job { const char *path; int *release; };
static void lookup(const char *path) {
    struct stat st;
    if (path && stat(path, &st)) abort();
}
static void *wait_job(void *arg) {
    struct job *job = arg;
    lookup(job->path);
    pthread_mutex_lock(&mutex);
    ++ready;
    pthread_cond_broadcast(&cond);
    while (!*job->release) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
    return NULL;
}
static void *exit_job(void *arg) {
    lookup(arg);
    return NULL;
}
static void start_waiting(pthread_t *thread, struct job *job, int expected_ready) {
    if (pthread_create(thread, NULL, wait_job, job)) exit(2);
    pthread_mutex_lock(&mutex);
    while (ready < expected_ready) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
}
static void run_and_join(const char *path) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, exit_job, (void *)path) || pthread_join(thread, NULL)) exit(2);
}
static void release(int *flag, pthread_t *threads, int count) {
    pthread_mutex_lock(&mutex);
    *flag = 1;
    pthread_cond_broadcast(&cond);
    pthread_mutex_unlock(&mutex);
    for (int i = 0; i < count; ++i) if (pthread_join(threads[i], NULL)) exit(2);
}
int main(int argc, char **argv) {
    if (argc != 8 && argc != 9) return 2;
    const char *cached = argv[1], *installed = argv[2], *method = argv[3];
    const char *evictor_path = argc == 9 ? argv[8] : installed;
    if (!strcmp(evictor_path, "none")) evictor_path = NULL;
    int stale = atoi(argv[4]), dummies = atoi(argv[5]);
    int holders = atoi(argv[6]), evictors = atoi(argv[7]);
    if (stale < 0 || stale > 1 || dummies < 0 || dummies > 64) return 2;
    if (holders < 0 || holders > 64 || evictors < 0 || evictors > 64) return 2;
    int release_stale = 0, release_rest = 0, expected = 0, count = 0;
    struct job stale_job = {cached, &release_stale};
    struct job evict_job = {evictor_path, &release_rest};
    struct job hold_job = {NULL, &release_rest};
    pthread_t stale_thread, others[128];
    memset(&stale_thread, 0, sizeof stale_thread);
    int late_exit = stale && evictors > 0;
    if (late_exit) start_waiting(&stale_thread, &stale_job, ++expected);
    else if (stale) run_and_join(cached);
    for (int i = 0; i < evictors; ++i) start_waiting(&others[count++], &evict_job, ++expected);
    if (late_exit) release(&release_stale, &stale_thread, 1);
    lookup(installed);
    for (int i = 0; i < dummies; ++i) run_and_join(NULL);
    for (int i = 0; i < holders; ++i) start_waiting(&others[count++], &hold_job, ++expected);
    char *args[] = {argv[2], NULL};
    if (!strcmp(method, "exec")) {
        execve(installed, args, environ);
        perror("execve"); return 2;
    }
    pid_t child;
    int error = posix_spawn(&child, installed, NULL, NULL, args, environ);
    if (error) { errno = error; perror("posix_spawn"); return 2; }
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 2;
    release(&release_rest, others, count);
    return WIFSIGNALED(status) ? 128 + WTERMSIG(status) : WEXITSTATUS(status);
}
