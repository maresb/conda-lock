/* Evict a live thread's hardlink origin using other live threads. */
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/attr.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/stat.h>
#include <unistd.h>
extern ssize_t fsgetpath(char *, size_t, fsid_t *, uint64_t);
static char paths[2][MAXPATHLEN];
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cond = PTHREAD_COND_INITIALIZER;
static int ready, release_workers;
static void *worker(void *unused) {
    (void)unused;
    struct stat st;
    if (stat(paths[0], &st)) abort();
    pthread_mutex_lock(&mutex);
    ++ready;
    pthread_cond_broadcast(&cond);
    while (!release_workers) pthread_cond_wait(&cond, &mutex);
    pthread_mutex_unlock(&mutex);
    return NULL;
}
static int which(const char *path) {
    return !strcmp(path, paths[0]) ? 0 : !strcmp(path, paths[1]) ? 1 : 2;
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    uint64_t links[2] = {0};
    for (int i = 0; i < 2; ++i) {
        if (!realpath(argv[i + 1], paths[i])) return 2;
        struct attrlist attr = {.bitmapcount = ATTR_BIT_MAP_COUNT,
            .commonattr = ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_FILEID,
            .forkattr = ATTR_CMNEXT_LINKID};
        struct __attribute__((packed, aligned(4))) {
            uint32_t length;
            attribute_set_t returned;
            uint64_t fileid, linkid;
        } result = {0};
        if (getattrlist(paths[i], &attr, &result, sizeof(result), FSOPT_ATTR_CMN_EXTENDED)) {
            perror("linkid attributes"); return 2;
        }
        if ((result.returned.commonattr & ATTR_CMN_FILEID) &&
            (result.returned.forkattr & ATTR_CMNEXT_LINKID)) links[i] = result.linkid;
        printf("{\"event\":\"linkid\",\"alias\":%d,\"fileid\":%llu,\"linkid\":%llu,\"returned_common\":%u,\"returned_fork\":%u}\n",
            i, (unsigned long long)result.fileid, (unsigned long long)links[i], result.returned.commonattr, result.returned.forkattr);
    }
    int fd = open(paths[1], O_RDONLY);
    struct stat st;
    struct statfs fs;
    if (fd < 0 || fstat(fd, &st) || fstatfs(fd, &fs)) return 2;
    printf("{\"event\":\"identity\",\"filesystem\":\"%s\",\"inode\":%llu,\"nlink\":%u}\n",
        fs.f_fstypename, (unsigned long long)st.st_ino, (unsigned int)st.st_nlink);
    int sizes[] = {0, 5, 6, 7, 8, 9};
    for (int trial = 0; trial < 20; ++trial) {
        for (size_t s = 0; s < sizeof(sizes) / sizeof(*sizes); ++s) {
            int count = sizes[s];
            pthread_t threads[64];
            struct stat unused;
            if (stat(paths[1], &unused)) return 2;
            char before[MAXPATHLEN], by_fd[MAXPATHLEN], by_id[MAXPATHLEN], by_link[2][MAXPATHLEN];
            if (fsgetpath(before, sizeof(before), &fs.f_fsid, st.st_ino) < 0) return 2;
            ready = release_workers = 0;
            for (int i = 0; i < count; ++i) {
                if (pthread_create(&threads[i], NULL, worker, NULL)) return 2;
                pthread_mutex_lock(&mutex);
                while (ready != i + 1) pthread_cond_wait(&cond, &mutex);
                pthread_mutex_unlock(&mutex);
            }
            /* Workers stay alive, excluding recycled thread identity here. */
            if (fcntl(fd, F_GETPATH, by_fd) || fsgetpath(by_id, sizeof(by_id), &fs.f_fsid, st.st_ino) < 0) return 2;
            int link_results[2] = {-1, -1};
            for (int i = 0; i < 2; ++i)
                if (links[i] && fsgetpath(by_link[i], sizeof(by_link[i]), &fs.f_fsid, links[i]) >= 0)
                    link_results[i] = which(by_link[i]);
            printf("{\"event\":\"origin\",\"trial\":%d,\"workers\":%d,\"before\":%d,\"parent_fd\":%d,\"parent_id\":%d,\"cache_linkid_path\":%d,\"env_linkid_path\":%d}\n",
                trial, count, which(before), which(by_fd), which(by_id), link_results[0], link_results[1]);
            pthread_mutex_lock(&mutex);
            release_workers = 1;
            pthread_cond_broadcast(&cond);
            pthread_mutex_unlock(&mutex);
            for (int i = 0; i < count; ++i) if (pthread_join(threads[i], NULL)) return 2;
        }
    }
    close(fd);
    return 0;
}
