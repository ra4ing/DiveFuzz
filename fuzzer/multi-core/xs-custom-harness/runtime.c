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
 * 2-hart custom litmus worker (no controller hart). Replaces litmus7's
 * harness with a bare-metal sense-reversing barrier, in-memory histogram,
 * and HTIF text output emitting the same rows the DiveFuzz parser matches.
 */

#include <stdint.h>
#include "runtime.h"
#include "seed_meta.h"   /* generated per seed: DFMC_NAME, DFMC_NHART,
                            DFMC_NOBS_TOTAL, DFMC_MAXOBS, dfmc_keys[], dfmc_obs_flat[] */

extern void litmus_P0(void);
extern void litmus_P1(void);
extern void dfmc_init(void);          /* generated per seed: zeroes/sets vars + obs */
extern void htif_putchar(char c);
extern void htif_exit(int code);

/* In .data with explicit init so it is correct at first entry without crt0.
   aligned(64) -> its own cache line, distinct from dfmc_var_N and dfmc_obs_flat. */
static volatile sense_t g_barrier __attribute__((aligned(64))) = { .c = DFMC_NHART, .sense = 0 };

static struct { uint64_t v[DFMC_MAXOBS]; int count; } g_hist[64];  /* hart0-only, in .bss */
static int g_hist_n = 0;
static uint64_t g_snap[DFMC_MAXOBS];

static void barrier_wait(volatile sense_t *p) {
    mbar();
    int sense = p->sense;
    mbar();
    int rem = __sync_add_and_fetch((volatile int *)&p->c, -1);
    mbar();
    if (rem == 0) { p->sense = 1 - sense; p->c = DFMC_NHART; }
    else { while (p->sense == sense) { /* spin */ } }
}

static void histogram_add(void) {
    int i, j;
    for (i = 0; i < DFMC_NOBS_TOTAL; i++) g_snap[i] = dfmc_obs_flat[i];
    for (i = 0; i < g_hist_n; i++) {
        int eq = 1;
        for (j = 0; j < DFMC_NOBS_TOTAL; j++) if (g_hist[i].v[j] != g_snap[j]) { eq = 0; break; }
        if (eq) { g_hist[i].count++; return; }
    }
    for (i = 0; i < DFMC_NOBS_TOTAL; i++) g_hist[g_hist_n].v[i] = g_snap[i];
    g_hist[g_hist_n].count = 1;
    g_hist_n++;
}

static void emit_str(const char *s) { while (*s) htif_putchar(*s++); }
static void emit_uint(uint64_t x) {
    char buf[24]; int n = 0;
    if (!x) { htif_putchar('0'); return; }
    while (x) { buf[n++] = (char)('0' + (x % 10)); x /= 10; }
    while (n) htif_putchar(buf[--n]);
}

static void emit_results(void) {
    int i, j;
    emit_str("Test "); emit_str(DFMC_NAME); emit_str(" Allowed\n");
    emit_str("Histogram ("); emit_uint((uint64_t)g_hist_n); emit_str(" states)\n");
    for (i = 0; i < g_hist_n; i++) {
        emit_uint((uint64_t)g_hist[i].count); emit_str(" :> ");
        for (j = 0; j < DFMC_NOBS_TOTAL; j++) {
            emit_str(dfmc_keys[j]); htif_putchar('='); emit_uint(g_hist[i].v[j]);
            htif_putchar(';'); htif_putchar(' ');
        }
        htif_putchar('\n');
    }
    emit_str("Observation "); emit_str(DFMC_NAME);
    emit_str(" Sometimes 0 0 "); emit_uint((uint64_t)NUMBER_OF_RUN); htif_putchar('\n');
}

static void worker(int hart) {
    int r;
    for (r = 0; r < NUMBER_OF_RUN; r++) {
        if (hart == 0) dfmc_init();
        barrier_wait(&g_barrier);                 /* START: init visible before window */
        if (hart == 0) litmus_P0(); else litmus_P1();
        barrier_wait(&g_barrier);                 /* END:   both windows complete */
        if (hart == 0) histogram_add();           /* hart0 reads dfmc_obs_flat */
        barrier_wait(&g_barrier);                 /* SYNC before next iteration */
    }
    if (hart == 0) { emit_results(); htif_exit(0); }
    else { for (;;) asm volatile("wfi"); }
}

void entry(int hart) { worker(hart); }
