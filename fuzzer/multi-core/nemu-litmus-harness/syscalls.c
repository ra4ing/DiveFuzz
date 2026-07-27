#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

static inline void nemu_putchar(char c) {
    *(volatile char *)0x310b0000UL = c;
}

void nemu_exit(int code) {
#ifdef __riscv
    register long a0 __asm__("x10") = code;
    __asm__ volatile(".word 0x0000006b" :: "r"(a0) : "memory");
#else
    (void)code;
#endif
    while (1) __asm__ volatile("wfi");
}

void _exit(int code) {
    nemu_exit(code);
}

int _write(int fd, const char *buf, int len) {
    (void)fd;
    for (int i = 0; i < len; i++) nemu_putchar(buf[i]);
    return len;
}

int fputc(int c, FILE *stream) {
    (void)stream;
    nemu_putchar((char)c);
    return (unsigned char)c;
}

int _read(int fd, char *buf, int len) {
    (void)fd; (void)buf; (void)len;
    errno = ENOSYS; return -1;
}

int _open(const char *name, int flags, int mode) {
    (void)name; (void)flags; (void)mode;
    errno = ENOSYS; return -1;
}

int _close(int fd) { (void)fd; return 0; }

long _lseek(int fd, long off, int whence) {
    (void)fd; (void)off; (void)whence;
    errno = ENOSYS; return -1;
}

int _fstat(int fd, struct stat *st) {
    (void)fd; st->st_mode = S_IFCHR; return 0;
}

int _isatty(int fd) { (void)fd; return 1; }

void _kill(int pid, int sig) { (void)pid; (void)sig; nemu_exit(1); }

int _getpid(void) { return 1; }

int _gettimeofday(struct timeval *tv, void *tz) {
    static const uint64_t NEMU_MTIME_HZ = 1000000ULL;
    (void)tz;
    if (tv) {
        uint64_t t;
        __asm__ volatile("rdtime %0" : "=r"(t));
        tv->tv_sec  = (long)(t / NEMU_MTIME_HZ);
        tv->tv_usec = (long)(t % NEMU_MTIME_HZ);
    }
    return 0;
}

int gettimeofday(struct timeval *tv, void *tz) {
    return _gettimeofday(tv, tz);
}
