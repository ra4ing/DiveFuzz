#include "harness_barrier.h"
#include "fiber.h"

int harness_sync_add_and_fetch(volatile int *p, int v) {
    int ret = __atomic_add_fetch(p, v, __ATOMIC_SEQ_CST);
    if (ret != 0) {
        fiber_yield();
    }
    return ret;
}
