/* Third design of the record probe. Every read by a probe thread is preceded
 * by a reset from the main thread, which looks up INSTALLED and builds the
 * path by inode itself, so that a thread without a record of its own reads
 * the environment path. A path build sets the fallback to the builder's
 * answer (fallback_state.c), so without these resets a thread's second read
 * could come from the fallback its first read installed. Every reset checks
 * its own answer and the program exits with status 3 if it is not the
 * environment path.
 *
 * record_state3 CACHED INSTALLED MODE [SLEEP_MS]
 *   The main thread opens INSTALLED and creates two idle threads, a helper
 *   and a verifier, used only by the oppose modes. Unless MODE is "control"
 *   or "oppose-control", a worker looks up CACHED and exits. The main thread
 *   resets. With SLEEP_MS and no holder, the main thread sleeps. Then:
 *     hold            a holder reads (h1), sleeps SLEEP_MS, reads (h2),
 *                     exits; main resets before each read and after it
 *     baseline        X does nothing
 *     read            X reads (x1), main resets, X reads (x2)
 *     refresh         X reads (x1), main resets, X looks up INSTALLED,
 *                     X reads (x2)
 *     control         as read, without a worker
 *     oppose          X reads (x1), main resets, X looks up INSTALLED, then
 *                     the helper looks up CACHED so that the fallback names
 *                     the cache alias, the verifier (which has no record)
 *                     reads (v), and X reads (x2): the environment path
 *                     means X holds a record of its own, the cache path
 *                     means it does not
 *     oppose-control  as oppose, without a worker and without X's lookup,
 *                     so X has no record and should read the cache path
 *   Main resets, then Y reads (y). Probe threads are created after the
 *   previous one was joined, so each may reuse the previous thread's
 *   identity; the helper and verifier exist throughout and cannot. */
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
enum { WANT_NONE, WANT_RESET, WANT_OPPOSE };
static int want, done;
static int helper_go, helper_done, verifier_go, verifier_done, all_exit;
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
    const char *answer = resolve();
    printf("reset=%s\n", answer);
    if (strcmp(answer, "env")) { fprintf(stderr, "reset read %s\n", answer); exit(3); }
}
static void wait_flag(int *flag) {
    while (!*flag) pthread_cond_wait(&cond, &mutex);
}
static void set_flag(int *flag) {
    *flag = 1;
    pthread_cond_broadcast(&cond);
}
/* Main thread, under the lock: make the fallback name the cache alias and
 * have the verifier confirm it. */
static void oppose(void) {
    set_flag(&helper_go);
    wait_flag(&helper_done);
    set_flag(&verifier_go);
    wait_flag(&verifier_done);
}
/* Called by a probe thread: ask the main thread for a reset or an oppose
 * step, and wait for it. */
static void request(int what) {
    pthread_mutex_lock(&mutex);
    want = what;
    pthread_cond_broadcast(&cond);
    while (want != WANT_NONE) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
}
static void finish(void) {
    pthread_mutex_lock(&mutex);
    set_flag(&done);
    pthread_mutex_unlock(&mutex);
}
/* Run a probe thread, serving its requests, and join it. */
static void run(void *(*fn)(void *)) {
    pthread_t thread;
    done = 0;
    want = WANT_NONE;
    if (pthread_create(&thread, NULL, fn, NULL)) exit(2);
    pthread_mutex_lock(&mutex);
    for (;;) {
        while (want == WANT_NONE && !done) pthread_cond_wait(&cond, &mutex);
        if (want == WANT_RESET) reset();
        else if (want == WANT_OPPOSE) oppose();
        if (want != WANT_NONE) {
            want = WANT_NONE;
            pthread_cond_broadcast(&cond);
        }
        if (done) break;
    }
    pthread_mutex_unlock(&mutex);
    if (pthread_join(thread, NULL)) exit(2);
}
static void *helper(void *unused) {
    (void)unused;
    pthread_mutex_lock(&mutex);
    while (!helper_go && !all_exit) pthread_cond_wait(&cond, &mutex);
    if (helper_go) {
        pthread_mutex_unlock(&mutex);
        lookup(paths[0]);
        pthread_mutex_lock(&mutex);
        set_flag(&helper_done);
    }
    wait_flag(&all_exit);
    pthread_mutex_unlock(&mutex);
    return NULL;
}
static void *verifier(void *unused) {
    (void)unused;
    pthread_mutex_lock(&mutex);
    while (!verifier_go && !all_exit) pthread_cond_wait(&cond, &mutex);
    if (verifier_go) {
        pthread_mutex_unlock(&mutex);
        printf("v=%s\n", resolve());
        pthread_mutex_lock(&mutex);
        set_flag(&verifier_done);
    }
    wait_flag(&all_exit);
    pthread_mutex_unlock(&mutex);
    return NULL;
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
    request(WANT_RESET);
    if (sleep_ms) usleep((useconds_t)sleep_ms * 1000);
    printf("h2=%s\n", resolve());
    finish();
    return NULL;
}
static void *thread_x(void *unused) {
    (void)unused;
    if (strcmp(mode, "baseline")) {
        printf("x1=%s\n", resolve());
        request(WANT_RESET);
        if (!strcmp(mode, "refresh") || !strcmp(mode, "oppose")) lookup(paths[1]);
        if (!strncmp(mode, "oppose", 6)) request(WANT_OPPOSE);
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
    pthread_t helper_thread, verifier_thread;
    if (pthread_create(&helper_thread, NULL, helper, NULL) ||
        pthread_create(&verifier_thread, NULL, verifier, NULL)) return 2;
    if (strcmp(mode, "control") && strcmp(mode, "oppose-control")) run(worker);
    reset();
    if (!strcmp(mode, "hold")) run(holder);
    else if (sleep_ms) usleep((useconds_t)sleep_ms * 1000);
    if (!strcmp(mode, "hold")) reset();
    run(thread_x);
    reset();
    run(thread_y);
    pthread_mutex_lock(&mutex);
    set_flag(&all_exit);
    pthread_mutex_unlock(&mutex);
    if (pthread_join(helper_thread, NULL) || pthread_join(verifier_thread, NULL)) return 2;
    close(fd);
    return 0;
}
