/* Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
 *
 * DiveFuzz is licensed under Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *          http://license.coscl.org.cn/MulanPSL2
 *
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
 * EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO,
 * MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
 *
 * See the Mulan PSL v2 for more details.
 *
 * Copy of spike-litmus-harness/syscalls.c with htif_putchar made non-static so
 * runtime.c can call it. The HTIF protocol is verbatim:
 *   htif_putchar: device 1 = console putchar, spin while tohost nonzero.
 *   htif_exit:    device 0 = exit, then wfi loop.
 */

#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>

extern volatile uint64_t tohost;
extern volatile uint64_t fromhost;

static void __htif_check_fromhost(void) {
    uint64_t fh = fromhost;
    if (!fh) return;
    fromhost = 0;
    /* cmd=0: console input available (ignored here)
     * cmd=1: console output ACK (just discard) */
}

void htif_putchar(char c) {
    uint64_t payload = (1ULL << 56) | (1ULL << 48) | (unsigned char)c;
    /* Wait until previous tohost command has been consumed */
    while (tohost) __htif_check_fromhost();
    tohost = payload;
    /* Fire-and-forget: spike will ACK async; next htif_putchar will drain it */
}

void htif_exit(int code) {
    /* Ensure all pending output is flushed before exit */
    while (tohost) {
        uint64_t fh = fromhost;
        if (fh) fromhost = 0;
    }

    __asm__ volatile("fence rw,rw" ::: "memory");
    uint64_t payload = ((uint64_t)(unsigned)code << 1) | 1;
    tohost = payload;

    /* Wait for spike to process the exit command.
     * Spike reads tohost, zeroes it, handles the command (which calls host exit).
     * If tohost clears, spike processed our command but didn't exit (shouldn't happen). */
    while (tohost) {
        __asm__ volatile("" ::: "memory");
    }
    while (1) {
        __asm__ volatile("wfi");
    }
}

void _exit(int code) {
    htif_exit(code);
}

int _write(int fd, const char *buf, int len) {
    (void)fd;
    for (int i = 0; i < len; i++) htif_putchar(buf[i]);
    return len;
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

void _kill(int pid, int sig) { (void)pid; (void)sig; htif_exit(1); }

int _getpid(void) { return 1; }

int _gettimeofday(struct timeval *tv, void *tz) {
    static const uint64_t SPIKE_MTIME_HZ = 1000000ULL;
    (void)tz;
    if (tv) {
        uint64_t t;
        __asm__ volatile("rdtime %0" : "=r"(t));
        tv->tv_sec  = (long)(t / SPIKE_MTIME_HZ);
        tv->tv_usec = (long)(t % SPIKE_MTIME_HZ);
    }
    return 0;
}

void *_sbrk(intptr_t increment) {
    extern char _heap_start;
    static char *heap_ptr = NULL;
    if (heap_ptr == NULL) heap_ptr = &_heap_start;
    char *old = heap_ptr;
    heap_ptr += increment;
    return (void *)old;
}
