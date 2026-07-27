#include "spike_hart.h"
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>

litmus_slot_t _litmus_slots[MAX_SECONDARY_HARTS] __attribute__((aligned(64)));

static unsigned int _next_hart = 1;

void launch(pthread_t *th, f_t *f, void *a) {
    unsigned int hartid = _next_hart++;
    if (hartid > MAX_SECONDARY_HARTS) {
        fputs("launch: out of secondary harts\n", stdout);
        exit(1);
    }
    litmus_slot_t *slot = &_litmus_slots[hartid];
    slot->done = 0;
    slot->arg  = a;
    __asm__ volatile("fence rw,rw" ::: "memory");
    slot->fn   = f;
    __asm__ volatile("fence rw,rw" ::: "memory");
    *th = (pthread_t)hartid;
}

void *join(pthread_t *th) {
    unsigned int hartid = (unsigned int)(*th);
    litmus_slot_t *slot = &_litmus_slots[hartid];
    while (!slot->done) {
        __asm__ volatile("fence r,r" ::: "memory");
    }
    slot->done = 0;
    if (hartid == _next_hart - 1) {
        _next_hart = 1;
    }
    return NULL;
}

void *mmap_exec(size_t sz) {
    void *p = malloc(sz);
    if (!p) { fputs("mmap_exec: malloc failed\n", stdout); exit(1); }
    return p;
}

void munmap_exec(void *p, size_t sz) {
    (void)sz;
    free(p);
}
