#ifndef _SYS_MMAN_H
#define _SYS_MMAN_H

#include <stddef.h>

#define PROT_READ   0x1
#define PROT_WRITE  0x2
#define PROT_EXEC   0x4
#define MAP_SHARED  0x01
#define MAP_ANONYMOUS 0x20
#define MAP_ANON    MAP_ANONYMOUS
#define MAP_FAILED  ((void *)-1)

static inline void *mmap(void *addr, size_t len, int prot, int flags, int fd, long off) {
    (void)addr; (void)len; (void)prot; (void)flags; (void)fd; (void)off;
    return MAP_FAILED;
}

static inline int munmap(void *addr, size_t len) {
    (void)addr; (void)len;
    return 0;
}

#endif
