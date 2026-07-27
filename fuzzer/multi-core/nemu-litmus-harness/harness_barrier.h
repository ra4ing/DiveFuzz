#ifndef HARNESS_BARRIER_H
#define HARNESS_BARRIER_H

#ifndef __ASSEMBLER__
int harness_sync_add_and_fetch(volatile int *p, int v);

#define __sync_add_and_fetch(ptr, val) \
    harness_sync_add_and_fetch((volatile int *)(ptr), (int)(val))
#endif

#endif
