/* What happens to a stale per-thread origin record when it is read, refreshed,
 * or held through a pause by the thread that inherited it?
 *
 * record_state CACHED INSTALLED MODE [SLEEP_MS]
 *   The main thread opens INSTALLED (a lookup of the environment alias).
 *   Unless MODE is "control", a worker looks up CACHED and exits, leaving a
 *   record that names the cache alias.
 *   Unless MODE is "norestore", the main thread then looks up INSTALLED
 *   again. A thread without a record of its own follows the most recent
 *   lookup, so after this step only a thread that inherited the worker's
 *   record can read the cache path. The first design of this probe lacked
 *   this step and could not tell the two apart.
 *   hold      a holder thread is created right after that lookup. It reads
 *             the path by inode (h1), sleeps SLEEP_MS with no filesystem
 *             activity, reads again (h2), and exits.
 *   Otherwise, with SLEEP_MS, the main thread sleeps before creating X.
 *   Thread X then runs and exits:
 *     baseline   does nothing
 *     read       reads the path twice (x1, x2)
 *     norestore  reads the path twice, without the restoring lookup above
 *     refresh    reads (x1), looks up INSTALLED itself, reads again (x2)
 *     control    reads twice (no worker ran)
 *     hold       reads twice
 *   Thread Y then reads the path once (y).
 *   Every thread is created after the previous one was joined, so each may
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
static int sleep_ms;
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
static void pause_ms(int ms) {
    if (ms) usleep((useconds_t)ms * 1000);
}
static void *worker(void *unused) {
    (void)unused;
    lookup(paths[0]);
    return NULL;
}
static void *holder(void *unused) {
    (void)unused;
    printf("h1=%s\n", resolve());
    pause_ms(sleep_ms);
    printf("h2=%s\n", resolve());
    return NULL;
}
static void *thread_x(void *unused) {
    (void)unused;
    if (!strcmp(mode, "baseline")) return NULL;
    printf("x1=%s\n", resolve());
    if (!strcmp(mode, "refresh")) lookup(paths[1]);
    printf("x2=%s\n", resolve());
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
    if (strcmp(mode, "norestore")) lookup(paths[1]);
    printf("restored=%s\n", resolve());
    if (!strcmp(mode, "hold")) run(holder);
    else pause_ms(sleep_ms);
    run(thread_x);
    run(thread_y);
    close(fd);
    return 0;
}
