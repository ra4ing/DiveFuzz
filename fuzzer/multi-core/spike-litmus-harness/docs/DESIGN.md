# 在 spike 上运行 RISC-V litmus 内存序测试

## 问题

**目标**：用 spike RISC-V 模拟器运行 `.litmus` 内存序测试，验证多线程场景下处理器的访存顺序行为。

**困难**：spike 是裸机模拟器，只加载 ELF 并在模拟的 hart 上直接执行机器码——没有操作系统，没有 Linux，没有 pthreads。而 litmus7 生成的测试代码依赖完整的 POSIX 环境：`pthread_create`/`pthread_join` 做线程管理，`printf` 做输出，`malloc` 做堆分配，`mmap` 做可执行内存映射。

**解决方案**：写一套裸机胶水层（harness），替换掉所有 OS 依赖，让 litmus7 的生成代码在 spike 上直接运行。

## 整体流程

```
LB-mixed1.litmus
    │
    ▼  litmus7 -mach riscv -mode presi -stdio false -avail 2 -o <gen_dir>
LB-mixed1.c + utils.c + litmus_io.c + ...
    │
    ▼  riscv64-linux-gnu-gcc -mcmodel=medany -static -ffreestanding ...
LB-mixed1.elf (bare-metal)
    │
    ▼  spike -p3 LB-mixed1.elf
Observation LB+mixed1 Never 0 40
```

分三个阶段，全部在 Docker 容器内执行：

1. **generate**：litmus7 把 `.litmus` 翻译成 C 源文件
2. **compile**：GCC 交叉编译为裸机 ELF
3. **run**：spike 加载 ELF，模拟多个 hart 并行执行，输出观测结果

## 逐层拆解

### 1. litmus7 生成阶段

litmus7 接收 `.litmus` 文件（一种描述多线程汇编测试的 DSL），生成等价的 C 代码。关键参数：

```
litmus7 -mach riscv -mode presi -stdio false -avail 2 -o <gen_dir> test.litmus
```

- `-mach riscv`：目标架构为 RISC-V
- `-mode presi`：presi 模式，线程通过 barrier 同步（不需要 OS 级调度）
- `-stdio false`：不使用 fprintf/printf，改用 `emit_string`/`emit_int` 等抽象 I/O 函数
- `-avail 2`：2 个 worker 线程

生成的主要文件：

| 文件 | 内容 |
|---|---|
| `<test>.c` | 测试主体：`main()` → `RUN()` → 循环调用 `launch(zyva)` / `join`，内含 `zyva()` → `choose()` → `do_run()` 的完整执行路径 |
| `utils.c` | 工具函数：`launch`/`join`（pthread 版）、`mmap_exec`、命令行解析、时间计数 |
| `litmus_io.c` | `emit_string`/`emit_int` 等非 stdio 输出函数 |
| `litmus_rand.c` | 随机数生成 |
| `platform_io.c` | 平台相关 I/O |
| `show.awk` | 从汇编中提取 `_litmus_P*` 函数体的 awk 脚本 |

litmus7 生成的 `<test>.c` 有一个特殊机制：它 `#include "<test>.h"` 来获取汇编代码的文本表示。这个 `.h` 文件不是 litmus7 直接生成的，需要二次构建（见下文）。

#### `.h` 文件的二次构建

`<test>.c` 里有一段内嵌汇编（`_litmus_P0`、`_litmus_P1` 等），以及一个 `#include "<test>.h"` 提供的 `ass(FILE *out)` 函数用于在输出中打印汇编。生成 `.h` 的流程是：

```
<test>.c ──gcc -DASS -S──> <test>.s ──show.awk──> <test>.t ──toh.sh──> <test>.h
```

1. 用 `-DASS` 编译 `<test>.c` 为汇编。`-DASS` 使 `ass()` 函数体为空，编译器会生成实际的汇编指令
2. `show.awk` 从汇编中提取以 `#START _litmus_P` 开头的代码段
3. `toh.sh`（来自 herdtools7 的 `_toh_nostdio.sh`）把提取的汇编行包装成 `static void ass(FILE *out) { emit_string(out, "..."); ... }`

在 `-stdio false` 模式下，最终编译时 `ass()` 函数用 `emit_string` 输出汇编文本，而非 `fprintf`。

### 2. 编译阶段

编译器是 `riscv64-linux-gnu-gcc`（Ubuntu 的 RISC-V 交叉编译包），搭配自编译的 newlib sysroot 提供头文件和 libc.a。

#### 为什么不用 `riscv64-unknown-elf-gcc`？

自编译的 `riscv64-unknown-elf-gcc`（来自 riscv-gnu-toolchain）缺少 `libgcc.a`——它只完成了 stage1 构建（C 语言支持），没有编译完提供软浮点等运行时函数的 libgcc。而 litmus7 生成的代码用到 `__extenddftf2`（double → long double 转换）、`__multf3`（long double 乘法）等符号。

Ubuntu 包 `gcc-13-riscv64-linux-gnu` 自带完整的 `libgcc.a`（`/usr/lib/gcc-cross/riscv64-linux-gnu/13/libgcc.a`），包含所有这些符号。所以我们用它做编译器，同时指向自编译的 newlib sysroot 提供裸机 C 库。

#### 编译选项要点

```
-march=rv64gc -mabi=lp64d    # RV64GC（含 FPU），double 浮点 ABI
-mcmodel=medany               # 任意地址模型，代码可放在 0x80000000 以后
-static -ffreestanding        # 纯静态裸机，不依赖任何运行时
-nostdinc                     # 不用系统头文件，全部用 -I/-isystem 指定
-DAVAIL=2                     # litmus7 需要的宏：并发线程数
-DFORCE_AFFINITY              # 启用 affinity 空实现
-include mbar.h               # 提供 mbar() 内存屏障宏
-Wl,--allow-multiple-definition  # harness 的 launch/join 覆盖 utils.c 的版本
```

`--allow-multiple-definition` 是关键：harness 的 `spike_hart.c` 先于 `utils.c` 传给链接器，所以 harness 的 `launch`/`join`/`mmap_exec`/`munmap_exec` 会覆盖 utils.c 里基于 pthread 的同名函数。

#### 链接顺序

```
startup.S  spike_hart.c  syscalls.c  affinity_stub.c  <test>.c  utils.c  litmus_io.c  ...
    │
    ├── -T linker.ld       # 裸机内存布局
    ├── -L newlib/lib -lc   # newlib 裸机 C 库
    ├── libgcc.a            # 软浮点等运行时
    └── libgcc_eh.a         # 异常处理支持
```

### 3. 运行阶段

```bash
spike -p3 LB-mixed1.elf
```

`-p3` 表示模拟 3 个 hart。这里 hart 0 是 orchestrator（运行 `main`），hart 1 和 2 是 worker（运行 `zyva`）。`AVAIL=2` 个 worker 需要 `AVAIL+1=3` 个 hart。

## 胶水层详解

harness 的核心任务是把 litmus7 生成的代码从 "Linux + pthreads" 环境搬到 "bare-metal + spike HTIF" 环境。需要替换的东西：

### startup.S — 裸机多 hart 入口

所有 hart 从 `_start` 开始执行。spike 会同时启动所有 hart（不像 Linux 里只有 hart 0 启动，其他靠 pthread_create）。

```
_start:
    csrr a0, mhartid          # 读 hart ID
    beqz a0, .Lhart0          # hart 0 → 初始化 + 调用 main

    # hart N>0:
    la gp, __global_pointer$  # 初始化全局指针
    la sp, _stack_top
    sub sp, sp, hartid*4096   # 每个 hart 独立栈
    j .Lsecondary_spin        # 进入工作循环

.Lhart0:
    la gp, __global_pointer$
    la sp, _stack_top
    # 清 BSS 段
    call main(1, {"litmus", NULL})
    call htif_exit            # main 返回后关机
```

secondary hart 的工作循环：

```
.Lsecondary_spin:
    s1 = &_litmus_slots[hartid]     # callee-saved! t1 会被 fn() 破坏
.Lwait_fn:
    fence rw, rw
    if (s1->fn == NULL) goto .Lwait_fn   # 自旋等待任务
    a0 = s1->arg
    s1->fn = 0                           # 清除 fn，下轮可重用
    jalr s1->fn(a0)                      # 调用 zyva()
    s1->done = 1                         # 标记完成
    goto .Lsecondary_spin                # 等待下一个任务
```

**为什么用 `s1` 而不是 `t1`？** `t1` 是 caller-saved 寄存器，`jalr` 调用 `zyva()` 后 `t1` 会被覆盖。如果用 `t1` 保存 slot 指针，`zyva()` 返回后 `t1` 已经是垃圾值，`done=1` 会写到错误地址。`s1` 是 callee-saved，函数调用后值不变。

**为什么传 `main(1, {"litmus", NULL})` 而不是 `main(0, NULL)`？** litmus7 生成的 `main()` 调用 `parse_opt(argc, argv)`，它会 `argv[0]` 取程序名，然后 `--argc; ++argv;`。如果 `argv` 为 NULL，`*argv` 导致段错误。

### spike_hart.c/h — launch/join 实现

litmus7 生成的代码通过 `launch(&th, zyva, &arg[id])` 启动 worker 线程，通过 `join(&th)` 等待完成。在 pthreads 环境下这分别是 `pthread_create` 和 `pthread_join`。我们用共享内存 + 自旋等待替代。

数据结构：

```c
typedef struct {
    volatile f_t *fn;      // offset  0: launch() 设置，secondary hart 自旋等待
    void         *arg;     // offset  8: 传递给 fn 的参数
    volatile int  done;    // offset 16: fn 返回后设为 1，join() 自旋等待
    char          _pad[12];// 对齐到 32 字节（避免 false sharing）
} litmus_slot_t;

litmus_slot_t _litmus_slots[8];  // 最多 8 个 secondary hart
```

`launch(pthread_t *th, f_t *f, void *a)`:
1. 取下一个 hart ID（从 `_next_hart=1` 开始递增）
2. 设置 `slot->done=0`, `slot->arg=a`, `fence`, `slot->fn=f`, `fence`
3. `*th = hartid`

两次 `fence rw,rw` 确保 `fn` 的写入不会被重排到 `arg` 之前——secondary hart 可能正在读这些字段。

`join(pthread_t *th)`:
1. 从 `*th` 取回 hart ID
2. 自旋等待 `slot->done != 0`（中间插入 `fence r,r` 确保看到最新值）
3. 清除 `done`，如果这是最后一个 join 的 hart，重置 `_next_hart=1`

`mmap_exec(size_t sz)` 和 `munmap_exec`：原版用 `mmap(PROT_READ|PROT_EXEC)` 分配可执行内存，我们直接用 `malloc` 替代——在裸机环境下所有内存都可执行。

### syscalls.c — HTIF 系统调用桩

newlib 的 C 库函数最终调用一组 `_` 前缀的系统调用桩。我们用 spike 的 HTIF（Host-Target Interface）协议实现最基本的功能。

HTIF 的工作原理：spike 在内存中保留两个 64 位变量 `tohost`（target → host）和 `fromhost`（host → target），物理地址由 linker.ld 中 `.tohost` 段指定。target 往 `tohost` 写命令，spike 主循环轮询并处理。

字符输出的 payload 格式：

```
bits [63:56] = device = 1  (console)
bits [55:48] = cmd    = 1  (putchar)
bits [47:40] = ch     = ASCII character
bits [39:0]  = 0
```

`htif_putchar` 的实现策略是 fire-and-forget：

```c
static void htif_putchar(char c) {
    uint64_t payload = (1ULL << 56) | (1ULL << 48) | (unsigned char)c;
    while (tohost) __htif_check_fromhost();  // 等上一个字符被 spike 取走
    tohost = payload;                         // 写入新字符，立即返回
}
```

`__htif_check_fromhost()` 在等待 `tohost` 清零时顺便消费 `fromhost` 上的 ACK。spike 的 HTIF 主循环：读到 `tohost != 0` → 清零 `tohost` → 处理命令 → 如果 ACK 队列非空且 `fromhost == 0` 则写 `fromhost`。所以 `tohost` 会在 spike 处理后自动清零，下次 `htif_putchar` 就能写入。

其他桩函数：

- `_write(fd, buf, len)`：逐字符调用 `htif_putchar`
- `_sbrk(increment)`：bump allocator，从 `_heap_start` 开始线性增长
- `_fstat(fd)`：返回 `S_IFCHR`（让 newlib 认为 stdout 是字符设备）
- `_gettimeofday(tv)`：用 `rdtime` 读 mtime 计数器，spike 默认 1MHz
- `_exit(code)`：写 `tohost = (code << 1) | 1`（spike 的关机命令）

### linker.ld — 内存布局

```
0x80000000  .text          代码段（含 .text.init 入口）
            .rodata        只读数据
            .tohost        tohost/fromhost 变量（64 字节对齐）
            .data          全局数据 + __global_pointer$
            .bss           未初始化数据
            .heap          8MB 堆空间
0x88000000  _stack_top     栈顶（128MB RAM 顶端 - 4KB）
```

`__global_pointer$` 放在 `.data` 段起始 + 0x800 处，这是 RISC-V GP-rel 寻址的标准偏移。linker relaxation（`.option norelax` 关闭时）会把 `la` 指令优化为 `gp + offset` 的单条指令。

### 辅助文件

- **mbar.h**：`mbar()` 即 `fence rw,rw`，litmus7 生成的 barrier 代码调用它
- **affinity.h / affinity_stub.c**：litmus7 的 CPU 亲和性接口。`-I$(HARNESS_DIR)` 在 `-I$(GEN_DIR)` 之前，所以我们的头文件覆盖 litmus7 生成的版本
- **pthread.h**：定义 `pthread_t`（实际是 `unsigned int`）和空的 `pthread_create`/`pthread_join`（不会被调用，但编译需要声明）
- **sys/mman.h**：定义 `mmap`/`munmap` 的常量和空实现，满足编译依赖

## 关键设计决策

**为什么用 `_litmus_slots[]` 而不是让 secondary hart 直接调 `pthread_create`？** 裸机环境下没有线程调度器。所有 hart 从同一入口 `_start` 开始执行，secondary hart 唯一能做的就是自旋等待任务。`_litmus_slots` 是 hart 0（main）和 secondary hart 之间的通信通道。

**为什么 spike 需要 `AVAIL+1` 个 hart？** litmus7 生成的 `main()` 在 hart 0 上运行。它循环调用 `launch(&th[id], zyva, &arg[id])`，把 `zyva` 函数分派给 hart 1..AVAIL。所以总共需要 1（orchestrator）+ AVAIL（worker）个 hart。

**为什么 `join()` 里 `_next_hart` 只在最后一个 join 时重置？** litmus7 的调用模式是：

```c
for (id = 0; id < AVAIL; id++) launch(&th[id], zyva, &arg[id]);
for (id = 0; id < AVAIL; id++) join(&th[id]);
```

所有 `join` 完成后 `_next_hart` 重置为 1，下一轮 `launch` 从 hart 1 重新开始。如果只 join 了部分 hart 就重置，会导致 hart ID 冲突。

**为什么用 `-mode presi` 而不是默认的 `std`？** presi（pre-silicon）模式使用用户态 barrier（`fence` 指令 + 自旋计数器），不依赖 OS 的同步原语。std 模式使用 pthread barrier，裸机环境不可用。
