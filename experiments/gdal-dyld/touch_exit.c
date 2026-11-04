/* Look up one path from a thread that then exits: models an installer process. */
#include <pthread.h>
#include <stdlib.h>
#include <sys/stat.h>
static const char *target;
static void *worker(void *unused) {
    (void)unused;
    struct stat st;
    if (stat(target, &st)) abort();
    return NULL;
}
int main(int argc, char **argv) {
    /* touch_exit PATH WORKERS: 0 looks up from the main thread; N uses N short-lived workers. */
    if (argc != 3) return 2;
    target = argv[1];
    int workers = atoi(argv[2]);
    if (workers < 0 || workers > 64) return 2;
    if (workers == 0) {
        struct stat st;
        if (stat(target, &st)) return 2;
    }
    for (int i = 0; i < workers; ++i) {
        pthread_t thread;
        if (pthread_create(&thread, NULL, worker, NULL) || pthread_join(thread, NULL)) return 2;
    }
    return 0;
}
