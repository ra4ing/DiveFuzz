#ifndef SPIKE_HART_H
#define SPIKE_HART_H

#include <stdint.h>
#include <stddef.h>
#include <pthread.h>

typedef void *f_t(void *);

typedef struct {
    volatile f_t *fn;      /* offset  0: NULL = idle, set by launch() */
    void         *arg;     /* offset  8 */
    volatile int  done;    /* offset 16: set to 1 by hart when fn returns */
    char          _pad[12];/* offset 20: pad to 32 bytes */
} __attribute__((aligned(32))) litmus_slot_t;

#define MAX_SECONDARY_HARTS 8

extern litmus_slot_t _litmus_slots[MAX_SECONDARY_HARTS];

void  launch(pthread_t *th, f_t *f, void *a);
void *join(pthread_t *th);
void *mmap_exec(size_t sz);
void  munmap_exec(void *p, size_t sz);

#endif
