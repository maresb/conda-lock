/* Does reading a stale per-thread origin through fsgetpath consume or refresh it?
 *
 * record_state CACHED INSTALLED MODE [SLEEP_MS]
 *   SLEEP_MS: optional pause after the worker exits, before X is created.
 *   The main thread opens INSTALLED (a lookup of the environment alias).
 *   Unless MODE is "control", a worker looks up CACHED and exits.
 *   Thread X then runs and exits:
 *     baseline  does nothing
 *     read      calls fsgetpath on the inode and reports the alias
 *     refresh   calls fsgetpath, then looks up INSTALLED
 *     control   calls fsgetpath (no worker ran)
 *     hold      a holder thread is created right after the worker exits and
 *               kept alive for SLEEP_MS with no filesystem activity, then
 *               released; X then calls fsgetpath. If X reads the cache path,
 *               the record survived the pause and the holder's identity was
 *               handed back to X.
 *   Thread Y then calls fsgetpath on the inode and reports the alias.
 *   X and Y are created after the previous thread was joined, so each may
 *   reuse the previous thread's kernel object. */
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
static const char *which(const char *path) {
    return !strcmp(path, paths[0]) ? "cache" : !strcmp(path, paths[1]) ? "env" : "other";
}
static const char *resolve(void) {
    static __thread char buffer[MAXPATHLEN];
    if (fsgetpath(buffer, sizeof buffer, &fsid, inode) < 0) { perror("fsgetpath"); exit(2); }
    return which(buffer);
}
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cond = PTHREAD_COND_INITIALIZER;
static int release_holder;
static void *holder(void *unused) {
    (void)unused;
    pthread_mutex_lock(&mutex);
    while (!release_holder) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
    return NULL;
}
static void *worker(void *unused) {
    (void)unused;
    struct stat st;
    if (stat(paths[0], &st)) abort();
    return NULL;
}
static void *thread_x(void *unused) {
    (void)unused;
    if (!strcmp(mode, "baseline")) { printf("x=none\n"); return NULL; }
    /* read, refresh, control, and hold all read the path here */
    printf("x=%s\n", resolve());
    if (!strcmp(mode, "refresh")) {
        struct stat st;
        if (stat(paths[1], &st)) abort();
    }
    return NULL;
}
static void *thread_y(void *unused) {
    (void)unused;
    printf("y=%s\n", resolve());
    return NULL;
}
static void run(void *(*fn)(void *)) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, fn, NULL) || pthread_join(thread, NULL)) exit(2);
}
int main(int argc, char **argv) {
    if (argc != 4 && argc != 5) return 2;
    for (int i = 0; i < 2; ++i) if (!realpath(argv[i + 1], paths[i])) return 2;
    mode = argv[3];
    int sleep_ms = argc == 5 ? atoi(argv[4]) : 0;
    if (sleep_ms < 0 || sleep_ms > 60000) return 2;
    int fd = open(paths[1], O_RDONLY);
    struct stat st;
    struct statfs fs;
    if (fd < 0 || fstat(fd, &st) || fstatfs(fd, &fs)) return 2;
    fsid = fs.f_fsid;
    inode = st.st_ino;
    printf("main=%s\n", resolve());
    if (strcmp(mode, "control")) run(worker);
    if (!strcmp(mode, "hold")) {
        pthread_t held;
        if (pthread_create(&held, NULL, holder, NULL)) return 2;
        if (sleep_ms) usleep((useconds_t)sleep_ms * 1000);
        pthread_mutex_lock(&mutex);
        release_holder = 1;
        pthread_cond_broadcast(&cond);
        pthread_mutex_unlock(&mutex);
        if (pthread_join(held, NULL)) return 2;
    } else if (sleep_ms) {
        usleep((useconds_t)sleep_ms * 1000);
    }
    run(thread_x);
    run(thread_y);
    close(fd);
    return 0;
}
