#include "nemu_hart.h"
#include "fiber.h"
#include <stddef.h>
#include <stdint.h>

litmus_slot_t _litmus_slots[MAX_SECONDARY_HARTS] __attribute__((aligned(64)));

fiber_t _fibers[MAX_FIBERS];
int _fiber_count = 0;
int _current_fiber = -1;
fiber_ctx_t _main_ctx;

static void fiber_entry(void) {
    int id = _current_fiber;
    if (id >= 0 && id < _fiber_count) {
        _fibers[id].fn(_fibers[id].arg);
        _fibers[id].done = 1;
    }
    fiber_yield();
    while (1) {
        fiber_yield();
    }
}

static int fibers_all_done(void) {
    for (int i = 0; i < _fiber_count; i++) {
        if (!_fibers[i].done) {
            return 0;
        }
    }
    return 1;
}

int fiber_is_running(void) {
    return _current_fiber >= 0;
}

void fiber_create(int id, void *(*fn)(void *), void *arg) {
    fiber_t *f = &_fibers[id];
    f->done = 0;
    f->fn = fn;
    f->arg = arg;

    f->ctx.s0 = 0;
    f->ctx.s1 = 0;
    f->ctx.s2 = 0;
    f->ctx.s3 = 0;
    f->ctx.s4 = 0;
    f->ctx.s5 = 0;
    f->ctx.s6 = 0;
    f->ctx.s7 = 0;
    f->ctx.s8 = 0;
    f->ctx.s9 = 0;
    f->ctx.s10 = 0;
    f->ctx.s11 = 0;
    f->ctx.ra = (uint64_t)(uintptr_t)fiber_entry;
    f->ctx.sp = ((uint64_t)(uintptr_t)(f->stack + FIBER_STACK_SIZE)) & ~0xFULL;
}

void fiber_yield(void) {
    if (_current_fiber < 0) {
        return;
    }
    int id = _current_fiber;
    _current_fiber = -1;
    fiber_switch(&_fibers[id].ctx, &_main_ctx);
}

void fiber_run_all(void) {
    while (!fibers_all_done()) {
        for (int i = 0; i < _fiber_count; i++) {
            if (_fibers[i].done) {
                continue;
            }
            _current_fiber = i;
            fiber_switch(&_main_ctx, &_fibers[i].ctx);
            _current_fiber = -1;
        }
    }
}

void fiber_run_until(int target_id) {
    if (target_id < 0 || target_id >= _fiber_count) {
        return;
    }

    while (!_fibers[target_id].done) {
        for (int i = 0; i < _fiber_count; i++) {
            if (_fibers[i].done) {
                continue;
            }
            _current_fiber = i;
            fiber_switch(&_main_ctx, &_fibers[i].ctx);
            _current_fiber = -1;
        }
    }
}

void launch(pthread_t *th, f_t *f, void *a) {
    if (_fiber_count >= MAX_FIBERS) {
        for (;;) {
            __asm__ volatile("wfi");
        }
    }

    int id = _fiber_count;
    fiber_create(id, f, a);
    _fiber_count++;
    *th = (pthread_t)(id + 1);
}

void *join(pthread_t *th) {
    if (!th) {
        fiber_run_all();
        return NULL;
    }

    int id = (int)(*th) - 1;
    if (id >= 0 && id < _fiber_count) {
        fiber_run_until(id);
    }
    return NULL;
}

void *mmap_exec(size_t sz) {
    extern char _heap_start;
    static char *bump = NULL;
    if (!bump) bump = &_heap_start;
    void *p = bump;
    bump += (sz + 7) & ~(size_t)7;
    return p;
}

void munmap_exec(void *p, size_t sz) {
    (void)p;
    (void)sz;
}
