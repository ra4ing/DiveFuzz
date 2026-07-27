#ifndef _STUB_SYS_MMAN_H
#define _STUB_SYS_MMAN_H
#include <stddef.h>
#define PROT_READ  1
#define PROT_WRITE 2
#define PROT_EXEC  4
#define MAP_SHARED    0x01
#define MAP_ANONYMOUS 0x20
#define MAP_FAILED ((void *)-1)
static inline void *mmap(void *addr, size_t len, int prot, int flags, int fd, long off) {
    (void)addr; (void)prot; (void)flags; (void)fd; (void)off;
    extern void *mmap_exec(size_t);
    return mmap_exec(len);
}
static inline int munmap(void *addr, size_t len) {
    (void)addr; (void)len; return 0;
}
#endif
