/* Create and join short-lived threads continuously, to model background
 * thread turnover, until terminated.  churn [THREADS_PER_CYCLE] */
#include <pthread.h>
#include <stdlib.h>
#include <unistd.h>
static void *nothing(void *unused) { (void)unused; return NULL; }
int main(int argc, char **argv) {
    int per_cycle = argc > 1 ? atoi(argv[1]) : 4;
    if (per_cycle < 1 || per_cycle > 64) return 2;
    pthread_t threads[64];
    for (;;) {
        for (int i = 0; i < per_cycle; ++i)
            if (pthread_create(&threads[i], NULL, nothing, NULL)) return 2;
        for (int i = 0; i < per_cycle; ++i)
            if (pthread_join(threads[i], NULL)) return 2;
        usleep(500);
    }
}
