#ifndef MBAR_H
#define MBAR_H

#ifndef __ASSEMBLER__
inline static void mbar(void) {
    __asm__ __volatile__("fence rw,rw" ::: "memory");
}
#endif

#endif
