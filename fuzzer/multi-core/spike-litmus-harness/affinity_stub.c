#include <stdlib.h>
#include "affinity.h"

cpus_t *cpus_create(int sz) {
    cpus_t *r = malloc(sizeof(*r));
    r->sz  = sz;
    r->cpu = malloc(sz * sizeof(int));
    return r;
}

#ifdef CPUS_DEFINED
cpus_t *read_affinity(void) {
    cpus_t *r = cpus_create(AVAIL);
    for (int i = 0; i < AVAIL; i++) r->cpu[i] = i;
    return r;
}

#ifdef FORCE_AFFINITY
cpus_t *read_force_affinity(int n_avail, int verbose) {
    (void)verbose;
    return cpus_create(n_avail);
}
#endif

void write_affinity(cpus_t *p) { (void)p; }
#endif

void write_one_affinity(int cpu) { (void)cpu; }

#ifdef FORCE_AFFINITY
void force_one_affinity(int cpu, int sz, int verbose, char *name) {
    (void)cpu; (void)sz; (void)verbose; (void)name;
}
#endif
