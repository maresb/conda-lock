/* Does a thread without an origin record of its own follow a lookup made by
 * a thread that has since exited, and does an extra fsgetpath by the main
 * thread change what the next thread inherits?
 *
 * fallback_state CACHED INSTALLED READER WORKER MAINREAD
 *   READER   pre   a reader thread is created before the worker and kept
 *                  alive, so it cannot inherit the worker's identity
 *            none  no reader
 *   WORKER   exited  a worker looks up CACHED and exits
 *            alive   a worker looks up CACHED and blocks until the end
 *            none    no worker
 *   MAINREAD 1     the main thread calls fsgetpath after the worker step,
 *                  as record_state does; 0 omits it
 *   Sequence: main opens INSTALLED; [reader created]; [worker, whose lookup
 *   the main thread waits for before going on]; [main read]; reader reads
 *   (r); X reads twice (x1, x2) and exits; Y reads (y).
 *   No thread looks up INSTALLED after the worker, so the most recent lookup
 *   of the inode is the worker's. */
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
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cond = PTHREAD_COND_INITIALIZER;
static int phase; /* 0 wait, 1 reader may read, 2 reader has read, 3 everyone may exit */
static int worker_looked_up; /* set by the live worker once its lookup has returned */
static const char *which(const char *path) {
    return !strcmp(path, paths[0]) ? "cache" : !strcmp(path, paths[1]) ? "env" : "other";
}
static const char *resolve(void) {
    static __thread char buffer[MAXPATHLEN];
    if (fsgetpath(buffer, sizeof buffer, &fsid, inode) < 0) { perror("fsgetpath"); exit(2); }
    return which(buffer);
}
static void wait_for(int target) {
    pthread_mutex_lock(&mutex);
    while (phase < target) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
}
static void advance(int target) {
    pthread_mutex_lock(&mutex);
    phase = target;
    pthread_cond_broadcast(&cond);
    pthread_mutex_unlock(&mutex);
}
static void *reader(void *unused) {
    (void)unused;
    wait_for(1);
    printf("r=%s\n", resolve());
    advance(2);
    wait_for(3);
    return NULL;
}
static void *worker_exit(void *unused) {
    (void)unused;
    struct stat st;
    if (stat(paths[0], &st)) abort();
    return NULL;
}
static void *worker_block(void *unused) {
    (void)unused;
    struct stat st;
    if (stat(paths[0], &st)) abort();
    pthread_mutex_lock(&mutex);
    worker_looked_up = 1;
    pthread_cond_broadcast(&cond);
    pthread_mutex_unlock(&mutex);
    wait_for(3);
    return NULL;
}
static void *thread_x(void *unused) {
    (void)unused;
    printf("x1=%s\n", resolve());
    printf("x2=%s\n", resolve());
    return NULL;
}
static void *thread_y(void *unused) {
    (void)unused;
    printf("y=%s\n", resolve());
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    for (int i = 0; i < 2; ++i) if (!realpath(argv[i + 1], paths[i])) return 2;
    const char *reader_mode = argv[3], *worker_mode = argv[4];
    int mainread = atoi(argv[5]);
    int fd = open(paths[1], O_RDONLY);
    struct stat st;
    struct statfs fs;
    if (fd < 0 || fstat(fd, &st) || fstatfs(fd, &fs)) return 2;
    fsid = fs.f_fsid;
    inode = st.st_ino;
    printf("main=%s\n", resolve());
    pthread_t reader_thread = NULL, worker_thread = NULL, thread;
    int have_reader = !strcmp(reader_mode, "pre");
    if (have_reader && pthread_create(&reader_thread, NULL, reader, NULL)) return 2;
    int worker_alive = !strcmp(worker_mode, "alive");
    if (!strcmp(worker_mode, "exited")) {
        if (pthread_create(&worker_thread, NULL, worker_exit, NULL) || pthread_join(worker_thread, NULL)) return 2;
    } else if (worker_alive) {
        if (pthread_create(&worker_thread, NULL, worker_block, NULL)) return 2;
        pthread_mutex_lock(&mutex);
        while (!worker_looked_up) pthread_cond_wait(&cond, &mutex);
        pthread_mutex_unlock(&mutex);
    }
    if (mainread) printf("mainread=%s\n", resolve());
    if (have_reader) { advance(1); wait_for(2); }
    if (pthread_create(&thread, NULL, thread_x, NULL) || pthread_join(thread, NULL)) return 2;
    if (pthread_create(&thread, NULL, thread_y, NULL) || pthread_join(thread, NULL)) return 2;
    advance(3);
    if (have_reader && pthread_join(reader_thread, NULL)) return 2;
    if (worker_alive && pthread_join(worker_thread, NULL)) return 2;
    close(fd);
    return 0;
}
