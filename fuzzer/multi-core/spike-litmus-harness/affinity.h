/* affinity.h — bare-metal stub for litmus7 affinity interface.
 * Defines cpus_t and declares the affinity functions.
 * This header takes precedence over the generated affinity.h
 * because -I$(HARNESS_DIR) comes before -I$(GEN_DIR).
 */
#ifndef _AFFINITY_H
#define _AFFINITY_H 1

#include <stdlib.h>

/* CPU set type used by litmus7 affinity interface */
typedef struct {
  int sz;
  int *cpu;
} cpus_t;

cpus_t *cpus_create(int sz);

#ifdef CPUS_DEFINED
cpus_t *read_affinity(void);
#ifdef FORCE_AFFINITY
cpus_t *read_force_affinity(int n_avail, int verbose);
#endif
void write_affinity(cpus_t *p);
#endif

void write_one_affinity(int cpu);
#ifdef FORCE_AFFINITY
void force_one_affinity(int cpu, int sz, int verbose, char *name);
#endif

#endif /* _AFFINITY_H */
