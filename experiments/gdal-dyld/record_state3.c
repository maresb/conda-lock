/* Third design of the record probe. Every read by a probe thread is preceded
 * by a reset from the main thread, which looks up INSTALLED and builds the
 * path by inode itself, so that a thread without a record of its own reads
 * the environment path. A path build sets the fallback to the builder's
 * answer (fallback_state.c), so without these resets a thread's second read
 * could come from the fallback its first read installed.
 *
 * record_state3 CACHED INSTALLED MODE [SLEEP_MS]
 *   The main thread opens INSTALLED. Unless MODE is "control", a worker looks
 *   up CACHED and exits. The main thread resets. With SLEEP_MS and no holder,
 *   the main thread sleeps. Then:
 *     hold      a holder reads (h1), sleeps SLEEP_MS, reads (h2), exits;
 *               main resets before each read and after the holder exits
 *     baseline  X does nothing
 *     read      X reads (x1), main resets, X reads (x2)
 *     refresh   X reads (x1), main resets, X looks up INSTALLED, X reads (x2)
 *     control   as read, without a worker
 *   Main resets, then Y reads (y). Threads are created after the previous
 *   one was joined, so each may reuse the previous thread's identity. */
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/stat.h>
#include <unistd.h>
extern ssize_t fsgetpath(char *, size_t, fsid_t *, uint64_t);
static char paths[2][MAXPATHLEN];
static fsid_t fsid;
static uint64_t inode;
static const char *mode;
static int sleep_ms;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cond = PTHREAD_COND_INITIALIZER;
static int want_reset, done;
static const char *which(const char *path) {
    return !strcmp(path, paths[0]) ? "cache" : !strcmp(path, paths[1]) ? "env" : "other";
}
static const char *resolve(void) {
    static __thread char buffer[MAXPATHLEN];
    if (fsgetpath(buffer, sizeof buffer, &fsid, inode) < 0) { perror("fsgetpath"); exit(2); }
    return which(buffer);
}
static void lookup(const char *path) {
    struct stat st;
    if (stat(path, &st)) { perror(path); exit(2); }
}
static void reset(void) {
    lookup(paths[1]);
    printf("reset=%s\n", resolve());
}
/* Called by a probe thread: ask the main thread to reset, and wait for it. */
static void request_reset(void) {
    pthread_mutex_lock(&mutex);
    want_reset = 1;
    pthread_cond_broadcast(&cond);
    while (want_reset) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
}
static void finish(void) {
    pthread_mutex_lock(&mutex);
    done = 1;
    pthread_cond_broadcast(&cond);
    pthread_mutex_unlock(&mutex);
}
/* Run a probe thread, serving its reset requests, and join it. */
static void run(void *(*fn)(void *)) {
    pthread_t thread;
    done = want_reset = 0;
    if (pthread_create(&thread, NULL, fn, NULL)) exit(2);
    pthread_mutex_lock(&mutex);
    for (;;) {
        while (!want_reset && !done) pthread_cond_wait(&cond, &mutex);
        if (want_reset) {
            reset();
            want_reset = 0;
            pthread_cond_broadcast(&cond);
        }
        if (done) break;
    }
    pthread_mutex_unlock(&mutex);
    if (pthread_join(thread, NULL)) exit(2);
}
static void *worker(void *unused) {
    (void)unused;
    lookup(paths[0]);
    finish();
    return NULL;
}
static void *holder(void *unused) {
    (void)unused;
    printf("h1=%s\n", resolve());
    request_reset();
    if (sleep_ms) usleep((useconds_t)sleep_ms * 1000);
    printf("h2=%s\n", resolve());
    finish();
    return NULL;
}
static void *thread_x(void *unused) {
    (void)unused;
    if (strcmp(mode, "baseline")) {
        printf("x1=%s\n", resolve());
        request_reset();
        if (!strcmp(mode, "refresh")) lookup(paths[1]);
        printf("x2=%s\n", resolve());
    }
    finish();
    return NULL;
}
static void *thread_y(void *unused) {
    (void)unused;
    printf("y=%s\n", resolve());
    finish();
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 4 && argc != 5) return 2;
    for (int i = 0; i < 2; ++i) if (!realpath(argv[i + 1], paths[i])) return 2;
    mode = argv[3];
    sleep_ms = argc == 5 ? atoi(argv[4]) : 0;
    if (sleep_ms < 0 || sleep_ms > 60000) return 2;
    int fd = open(paths[1], O_RDONLY);
    struct stat st;
    struct statfs fs;
    if (fd < 0 || fstat(fd, &st) || fstatfs(fd, &fs)) return 2;
    fsid = fs.f_fsid;
    inode = st.st_ino;
    printf("main=%s\n", resolve());
    if (strcmp(mode, "control")) run(worker);
    reset();
    if (!strcmp(mode, "hold")) run(holder);
    else if (sleep_ms) usleep((useconds_t)sleep_ms * 1000);
    if (!strcmp(mode, "hold")) reset();
    run(thread_x);
    reset();
    run(thread_y);
    close(fd);
    return 0;
}
