# 在 NEMU 上运行 RISC-V litmus 内存序测试

## 问题

**目标**：把 `.litmus` 内存序测试跑在 NEMU 上，验证 RVWMO 下的访存顺序行为。

这件事和 spike 版 harness 的目标一致，但 NEMU 版不是简单照搬。我们要同时满足两个条件。第一，继续沿用 litmus7 生成测试代码的整体形态。第二，适配 NEMU 的运行模型，尤其是单 hart 进程模型、UART16550 控制台和 `nemu_trap` 退出机制。

和 spike 相比，NEMU 的关键差异不是指令集，而是“怎么把多线程测试塞进一个单 hart 进程里”。这也是这个版本最有意思的地方。为了让 litmus7 生成的 barrier 测试不死锁，我们引入了协作式纤程调度器。这一层是 NEMU 版和 spike 版最大的架构分叉。

## 整体流程

```
LB-mixed1.litmus
    │
    ▼  litmus7 -mach riscv -mode presi -stdio false -avail 2 -o <gen_dir>
LB-mixed1.c + utils.c + litmus_io.c + ...
    │
    ▼  riscv64-unknown-elf-gcc + picolibc
LB-mixed1.elf / LB-mixed1.bin
    │
    ▼  NEMU -b LB-mixed1.bin
Observation LB+mixed1 Never 0 40
```

整体还是三段式，但有两处和 spike 不同。

1. 编译链从 `riscv64-linux-gnu-gcc` 变成 `riscv64-unknown-elf-gcc + picolibc`，因为 NEMU harness 是裸机程序，不挂 Linux。
2. 运行时不再依赖 spike 的多 hart 同机模拟，而是按 NEMU 的单 hart 进程模型处理调度。

这套流程的结果和 spike 一样，最终 verdict 仍然是 `Observation LB+mixed1 Never 0 40`。

## 逐层拆解

### 1. litmus7 生成阶段

这一层和 spike 基本相同。litmus7 仍然把 `.litmus` 翻译成 C 文件，核心参数也是 `-mach riscv -mode presi -stdio false -avail 2`。

`presi` 模式的意义没有变，还是用 barrier 驱动并发测试。差异在于，NEMU 版生成代码最后不会直接依赖 pthread，而是交给后面的胶水层把线程语义改写成 fiber 语义。

生成出来的文件仍然包括主测试文件、`utils.c`、`litmus_io.c`、`platform_io.c` 和 `litmus_rand.c`。这些文件的行为和 spike 版大体一致，真正变化发生在编译和运行时的替换层。

### 2. 编译阶段

NEMU 版使用 `riscv64-unknown-elf-gcc`，并链接 `picolibc`。

```make
GCC     ?= riscv64-unknown-elf-gcc
PICOLIBC ?= /usr/lib/picolibc/riscv64-unknown-elf
```

这里和 spike 版最大的不一样是 libc 选择。NEMU harness 是裸机环境，不能把 glibc 当成默认运行时。`picolibc` 更适合这种无操作系统、无动态链接的场景。链接脚本也以 `0x80000000` 作为 RAM 基址，和 NEMU 默认物理内存起点一致。

### 3. 运行阶段

NEMU 版把测试编成 flat binary，然后直接丢给 NEMU。

```bash
$(NEMU) -b $(BIN)
```

`-b` 表示 batch 模式，避免交互提示。由于 NEMU 的内存分配和退出机制都和 spike 不同，这一步不能再沿用 spike 的 HTIF 语义。

### 4. verdict 阶段

verdict 解析仍然是从控制台输出里找 `Observation ...`。这一层和 spike 一样，最终都落到同一条结果线：`Observation LB+mixed1 Never 0 40`。

## 胶水层详解

这一层负责把 litmus7 的 pthread 风格测试，搬到 NEMU 的裸机环境里。下面逐个文件说。

### `startup.S`，裸机入口，NEMU-specific delta

这个文件是 NEMU 版启动代码的入口。它做三件事，读 `mhartid`，清 BSS，调用 `main()`。

```asm
_start:
    csrr    a0, mhartid
    beqz    a0, .Lhart0

.Lhart0:
    la      sp, _stack_top
    la      a0, _bss_start
    la      a1, _bss_end
    call    main
    call    nemu_exit
```

对 spike 来说，secondary hart 也会真正并行执行同一段二进制。NEMU 版则更偏向单 hart 进程模型，所以这里的入口更强调“主 hart 负责调度，其他执行单元由 harness 模拟”。

### `linker.ld`，内存布局，和 spike 基本一致但面向 NEMU

```ld
MEMORY {
    RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 128M
}
```

这和 NEMU 的默认 `CONFIG_MBASE` 对齐，方便直接把镜像映射到 NEMU 的 RAM 起点。和 spike 一样，`.text`、`.data`、`.bss`、`.heap` 都在同一个裸机地址空间内展开。

### `nemu_hart.c` / `nemu_hart.h`，NEMU-specific delta，核心调度层

这是 NEMU 版最关键的文件。它不是简单的 `launch` / `join` 替代，而是一个协作式 fiber 调度器。

`nemu_hart.h` 里把 `pthread_t` 直接定义成 `unsigned long`，实际含义是 fiber id 加 1。

```c
typedef unsigned long pthread_t;
```

`launch()` 只创建 fiber，不立即运行。`join()` 则负责驱动调度器。

```c
void launch(pthread_t *th, f_t *f, void *a) {
    int id = _fiber_count;
    fiber_create(id, f, a);
    _fiber_count++;
    *th = (pthread_t)(id + 1);
}

void *join(pthread_t *th) {
    int id = (int)(*th) - 1;
    if (id >= 0 && id < _fiber_count) {
        fiber_run_until(id);
    }
    return NULL;
}
```

这段实现说明了一个事实，NEMU 版里的“线程”其实是可调度的协作式任务，不是内核线程。

### `fiber.h` / `fiber.S`，NEMU-specific delta，新引入的上下文切换层

`fiber.h` 定义了 fiber 上下文。它保存 `s0` 到 `s11`，再加 `ra` 和 `sp`，一共 14 个寄存器。

14 × 8 字节 = 112 字节，这就是 fiber 上下文的最小代价。

```c
typedef struct {
    uint64_t s0;
    uint64_t s1;
    ...
    uint64_t s11;
    uint64_t ra;
    uint64_t sp;
} fiber_ctx_t;
```

`fiber.S` 做真正的保存和恢复。

```asm
sd s0,   0(a0)
sd s1,   8(a0)
...
sd s11, 88(a0)
sd ra,  96(a0)
sd sp, 104(a0)

ld s0,   0(a1)
ld s1,   8(a1)
...
ld s11, 88(a1)
ld ra,  96(a1)
ld sp, 104(a1)
ret
```

这里的意义很直接。NEMU 上没有现成的 pthread 调度器可借，fiber 就是我们自己造出来的“轻量线程”。

### `harness_barrier.h` / `harness_barrier.c`，NEMU-specific delta，注入 yield 的钩子

这个层解决的是 barrier 自旋死锁。

```c
#define __sync_add_and_fetch(ptr, val) \
    harness_sync_add_and_fetch((volatile int *)(ptr), (int)(val))
```

实现里在原子加完以后，如果返回值不是 0，就调用 `fiber_yield()`。

```c
int harness_sync_add_and_fetch(volatile int *p, int v) {
    int ret = __atomic_add_fetch(p, v, __ATOMIC_SEQ_CST);
    if (ret != 0) {
        fiber_yield();
    }
    return ret;
}
```

这一步非常关键。它把原本纯自旋的 barrier_wait 改造成“让出执行权”，从而让另一条 fiber 有机会到达 barrier。

### `syscalls.c`，NEMU-specific delta，退出和控制台

NEMU 的退出不是 HTIF，而是 `nemu_trap`。

```c
void nemu_exit(int code) {
#ifdef __riscv
    register long a0 __asm__("x10") = code;
    __asm__ volatile(".word 0x0000006b" :: "r"(a0) : "memory");
#endif
    while (1) __asm__ volatile("wfi");
}
```

控制台输出也不是 spike 的 `tohost`，而是 UART16550 MMIO。

```c
static inline void nemu_putchar(char c) {
    *(volatile char *)0x310b0000UL = c;
}
```

这两个机制分别对应 NEMU 的退出和字符输出路径，和 spike 版完全不同。

### `mbar.h`，和 spike 相同

`mbar()` 仍然只是一个 `fence rw,rw`。

```c
inline static void mbar(void) {
    __asm__ __volatile__("fence rw,rw" ::: "memory");
}
```

这一层和 spike 相同，目的是让 litmus7 生成的屏障代码保持一致语义。

### `pthread.h`，NEMU-specific delta，空壳接口

这个头文件只是为了让生成代码过编译。

`pthread_t` 仍然是 `unsigned long`，但 `pthread_create` 和 `pthread_join` 都是 stub。真实调度已经被 `nemu_hart.c` 接管了。

### `sys/mman.h`，NEMU-specific delta，mmap 退化为 bump allocator

```c
static inline void *mmap(void *addr, size_t len, int prot, int flags, int fd, long off) {
    extern void *mmap_exec(size_t);
    return mmap_exec(len);
}
```

这层直接把可执行内存分配降级成 bump allocator。NEMU 裸机没有真正的虚拟内存子系统，所以这个退化是合理的。

### `affinity.h` / `affinity_stub.c`，NEMU-specific delta，CPU 亲和性空实现

litmus7 会碰 CPU affinity 接口，但 NEMU 裸机环境里没有 Linux 亲和性概念，所以这里是 stub。

`read_affinity()` 返回从 0 到 `AVAIL-1` 的顺序 CPU 列表，`write_affinity()` 什么也不做。

## NEMU 运行机制三大要点

这一节引用 NEMU 源码，说明为什么前面的设计必须这样写。

### 1. 退出机制，`nemu_trap`

NEMU 的程序退出依赖 `nemu_trap` 伪指令，退出码放在 `a0`。`cpu-exec.c` 里对 `nemu_trap` 的处理会把它当作检查点和程序结束点，见 `nemu/src/cpu/cpu-exec.c:317-320`。

这和 spike 的 HTIF 关机命令完全不是一回事。NEMU 版的 `nemu_exit()` 因此必须发出 `.word 0x0000006b`，而不是写 `tohost`。相关结论也来自 `PROBE_RESULTS.md:15-18`。

### 2. 控制台机制，UART16550 MMIO

NEMU 的字符输出走 UART16550 的 THR 寄存器，写地址是 `0x310b0000`。源码里 `serial_handle_standard_access()` 在 `case UART_THR` 下直接 `putc(..., stderr)`，见 `nemu/src/device/uart16550.c:197-207`。

这解释了为什么 `syscalls.c` 里要把 `_write()` 和 `fputc()` 都接到同一个 `nemu_putchar()` 上。`PROBE_RESULTS.md:16-18` 也确认了这个结论。

### 3. 单 hart 进程模型

NEMU 的内存分配使用 `mmap(..., MAP_ANONYMOUS | MAP_PRIVATE | MAP_NORESERVE, ...)`，见 `nemu/src/memory/paddr.c:186-195`。

这意味着每个 NEMU 进程有自己的私有地址空间，不能像某些共享内存方案那样指望多个 hart 在同一个进程里自然共享状态。`PROBE_RESULTS.md:12-13` 已经明确指出，NEMU 是单 hart per process，然后通过 `-p N` 起多个实例来扩展。

如果未来 NEMU 的 A-extension、multi-hart 或 exit 支持发生变化，记得重新跑 `PROBE_RESULTS.md` 里的探针。

## 核心挑战，Barrier 死锁与协作式纤程调度器

这就是 NEMU 版和 spike 版最大的架构差异。

### 问题是什么

litmus7 生成的 `barrier_wait()` 本质上是自旋等待。它会先用原子加减修改计数，然后在 `while (p->sense == sense)` 里等其他线程到齐。

在 spike 的多 hart 模型里，这没问题，因为 hart 真的是并行运行的。可在 NEMU 里，如果你按顺序 `launch()` 两个 worker，而不让第一个 worker 中途让出控制权，第二个 worker 根本没有机会运行，barrier 就会永远卡住。

### 为什么不能换别的方法

1. 不能改 NEMU 源码，这是约束。
2. 不能靠 `MAP_SHARED` 做多进程共享，因为 NEMU 的内存路径是私有映射，见 `nemu/src/memory/paddr.c:191-192`。
3. 不能直接改生成文件里的 `static barrier_wait()`，因为它是 litmus7 生成的静态函数，不能靠外部重写。
4. 不能靠 pthread 或信号做抢占，因为这是裸机。

### 解决方案是什么

我们自己造一个协作式纤程调度器。

`launch()` 只负责创建 fiber，不立即运行。`join()` 负责驱动调度循环。`fiber_yield()` 是唯一显式让出点。

调度器的核心数据结构很简单。每个 fiber 有独立栈，`FIBER_STACK_SIZE` 是 65536 字节，足够覆盖 litmus 测试的调用深度。

### 为什么把 yield 注入到 `__sync_add_and_fetch`

因为 barrier 的等待路径本身几乎没有可插入的函数调用点。直接改 spin loop 风险大，而且生成文件不方便维护。

而 `__sync_add_and_fetch` 可以通过宏重定义拦截。

```c
#define __sync_add_and_fetch(ptr, val) \
    harness_sync_add_and_fetch((volatile int *)(ptr), (int)(val))
```

于是原来的 barrier 逻辑变成：最后一个到达者继续推进，非最后一个到达者在原子操作后主动 `fiber_yield()`。

### 两个 fiber 过 barrier 的时序

```text
fiber-0                scheduler                fiber-1
   |                     |                        |
   | launch              |                        |
   |-------------------->|                        |
   | barrier_wait        |                        |
   | __sync_add... => 1  |                        |
   | fiber_yield         |                        |
   |-------------------->| run next fiber         |
   |                     |----------------------->|
   |                     |      barrier_wait      |
   |                     |      __sync_add...=>0  |
   |                     |      set sense         |
   |                     |<-----------------------|
   | resume              |                        |
   | sense changed, exit  |                        |
```

这个时序说明了为什么协作式调度器能解死锁。只要某个 fiber 在 barrier 早到，就主动让出，另一个 fiber 就能完成最后一次到达并翻转 sense。

## 关键设计决策

### 为什么不用 `riscv64-linux-gnu-gcc`

因为 NEMU harness 是裸机程序，不是 Linux 用户态程序。`riscv64-linux-gnu-gcc` 默认面向 glibc 和 Linux ABI，和这种无操作系统镜像不合适。`riscv64-unknown-elf-gcc + picolibc` 更贴近裸机交叉编译场景。

### 为什么用协作式 fiber，而不是抢占式线程

因为 NEMU 里没有可直接依赖的定时器中断路径来做抢占。协作式 fiber 的优势是可控、简单，而且和 litmus7 的 barrier 模型天然契合。

### 为什么在 `__sync_add_and_fetch` 上做宏注入

因为这是 barrier wait 路径上最稳定的拦截点。spin loop 里没有现成的函数钩子，而原子递增本来就必须经过这一层，所以这里插入 `fiber_yield()` 最自然。

### 为什么 fiber 栈是 64KB

这是经验值。litmus 测试的栈深度很浅，64KB 足够安全，也不会让每个 fiber 的内存成本过高。

### 为什么 future 里可以替换掉 fiber 调度器

如果未来 NEMU 真正提供更完整的 multi-hart 支持，或者调度和退出机制发生变化，这一层可以被替换成更接近真实 SMP 的实现。当前方案的价值在于，它已经把 litmus7 的语义稳定地跑通了。

## 结果与约束

最终输出是 `Observation LB+mixed1 Never 0 40`，和 spike 版一致。这说明 NEMU harness 没有改变 litmus 测试的语义，只是换了一套运行底座。

同时，`PROBE_RESULTS.md` 里的结论也说明当前 NEMU 版本没有阻塞性问题，`nemu_trap`、UART16550 和 `mhartid` 都能满足这个 harness 的需要。若未来 NEMU 的 A-extension、multi-hart 或 exit 路径变化，先重跑探针，再改文档和实现。
