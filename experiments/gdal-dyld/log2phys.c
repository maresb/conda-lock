/* Print a file's physical extents as JSON lines using F_LOG2PHYS_EXT against
 * the native struct log2phys, which Apple declares with 4-byte packing.
 *   {"file_offset": N, "device_offset": N, "length": N}  per extent
 *   {"size": N, "complete": true|false, "struct_size": N}  last line
 * Usage: log2phys PATH */
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    int fd = open(argv[1], O_RDONLY);
    struct stat st;
    if (fd < 0 || fstat(fd, &st)) { perror(argv[1]); return 1; }
    off_t size = st.st_size, offset = 0;
    int complete = 1;
    while (offset < size) {
        struct log2phys l2p = {0, size - offset, offset};
        if (fcntl(fd, F_LOG2PHYS_EXT, &l2p) < 0) { perror("F_LOG2PHYS_EXT"); complete = 0; break; }
        if (l2p.l2p_contigbytes <= 0) { complete = 0; break; }
        if (l2p.l2p_contigbytes > size - offset) l2p.l2p_contigbytes = size - offset;
        printf("{\"file_offset\": %lld, \"device_offset\": %lld, \"length\": %lld}\n",
               (long long)offset, (long long)l2p.l2p_devoffset, (long long)l2p.l2p_contigbytes);
        offset += l2p.l2p_contigbytes;
    }
    printf("{\"size\": %lld, \"complete\": %s, \"struct_size\": %zu}\n",
           (long long)size, complete ? "true" : "false", sizeof(struct log2phys));
    close(fd);
    return 0;
}
