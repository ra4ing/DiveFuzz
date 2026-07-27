#ifndef FIBER_H
#define FIBER_H

#include <stdint.h>

#define MAX_FIBERS 8
#define FIBER_STACK_SIZE 65536

typedef struct {
    uint64_t s0;
    uint64_t s1;
    uint64_t s2;
    uint64_t s3;
    uint64_t s4;
    uint64_t s5;
    uint64_t s6;
    uint64_t s7;
    uint64_t s8;
    uint64_t s9;
    uint64_t s10;
    uint64_t s11;
    uint64_t ra;
    uint64_t sp;
} fiber_ctx_t;

typedef struct {
    fiber_ctx_t ctx;
    unsigned char stack[FIBER_STACK_SIZE];
    int done;
    void *(*fn)(void *);
    void *arg;
} fiber_t;

extern fiber_t _fibers[MAX_FIBERS];
extern int _fiber_count;
extern int _current_fiber;  /* -1 = scheduler/main */
extern fiber_ctx_t _main_ctx;

void fiber_switch(fiber_ctx_t *old_ctx, fiber_ctx_t *new_ctx);
void fiber_yield(void);
int  fiber_is_running(void);
void fiber_create(int id, void *(*fn)(void *), void *arg);
void fiber_run_until(int target_id);
void fiber_run_all(void);

#endif
