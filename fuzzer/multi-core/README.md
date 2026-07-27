# 在 Spike 与 NEMU 上运行 RISC-V Litmus 内存序测试

本工作区记录了一项完整的工程实践：把 [`litmus-tests-riscv`](litmus-tests-riscv/) 中的 `.litmus` 内存序测试用例，分别搬到两款 RISC-V 模拟器——[Spike](https://github.com/riscv-software-src/riscv-isa-sim) 和 [NEMU](https://github.com/OpenXiangShan/NEMU)——上跑通，并产出可复现的 `Observation` verdict。文档统一收敛在此 README，下属两个子项目 [`spike-litmus-harness/`](spike-litmus-harness/) 和 [`nemu-litmus-harness/`](nemu-litmus-harness/) 各自还保留更细的 `docs/DESIGN.md` 与 `docs/MANUAL.md`，本文不重复那些细节，而是讲清楚“为什么要这么做、两边怎么分叉、以及作为使用者应该怎么上手”。

---

## 1. 背景与目标

`litmus` 测试是研究和验证处理器内存模型（Memory Consistency Model）最常用的工具。每个 `.litmus` 文件都描述了一段多线程的汇编片段，再加上一个“允许 / 禁止”的最终状态条件；工具 `litmus7`（来自 herdtools7）会把它翻译成一段可以在真实硬件或模拟器上反复运行的 C 程序，不断记录最终寄存器/内存状态，最后给出直方图和 verdict。

这套流程在 Linux 上已经很成熟：`litmus7` 生成的 C 代码直接调用 `pthread_create`、`pthread_join`、`mmap`、`printf`，只要有一台 Linux 机器和 pthread 就能跑。问题在于，我们要跑的是**两个裸机模拟器**：

- **Spike** 是 RISC-V 官方参考模拟器，只加载 ELF 并在模拟的 hart 上直接执行机器码，没有内核、没有 pthread。
- **NEMU** 是 OpenXiangShan 用来做差分测试的模拟器，单 hart per process，退出机制和控制台是自己约定的（`nemu_trap` 伪指令、UART16550 MMIO）。

两者都没有“线程”这个概念，也没有 libc。要让 `litmus7` 生成的代码在它们上面跑通，就得写一层 **harness**：一套胶水代码，把 pthread、libc、mmap、标准输出这些 Linux 侧的运行时依赖，替换成各自模拟器能吃进去的裸机等价物。

本工作区里两个 harness 的目标与最终结果是一致的——都能把同一份 `.litmus` 测试跑出同样的 verdict：

```
Observation LB+mixed1 Never 0 40
```

一致的结果，说明 harness 并没有改变 litmus 测试的语义，只是给它换了一副运行底座。

---

## 2. 工作区总览

```
kaixinyuan/
├── README.md                  ← 你正在读的这份整体文档
├── PROGRESS.md                ← 开发期逐步记录的进度笔记（spike 版）
│
├── litmus-tests-riscv/        ← 上游 litmus 测试用例（.litmus 源文件）
│
├── spike-litmus-harness/      ← Spike 版 harness（多 hart 裸机方案）
│   ├── docs/{DESIGN,MANUAL}.md
│   ├── startup.S, linker.ld
│   ├── spike_hart.{c,h}, spike_htif.h
│   ├── syscalls.c, affinity_stub.c, ...
│   └── Makefile, run_litmus.sh
│
├── nemu-litmus-harness/       ← NEMU 版 harness（单 hart + 纤程调度方案）
│   ├── docs/{DESIGN,MANUAL}.md
│   ├── PROBE_RESULTS.md       ← NEMU 接口探针结论
│   ├── startup.S, linker.ld
│   ├── nemu_hart.{c,h}, nemu_htif.h
│   ├── fiber.{h,S}, harness_barrier.{c,h}
│   ├── syscalls.c, affinity_stub.c, ...
│   └── Makefile
│
├── riscv-isa-sim/             ← Spike 源码（可按需清理，编译结果已装到 riscv/）
├── riscv-pk/                  ← riscv-pk 源码
├── riscv-gnu-toolchain/       ← 自编译工具链源码
├── riscv/                     ← 编译产物：spike 二进制 + newlib sysroot
└── nemu/                      ← NEMU 源码与构建产物
```

开发和测试都在 Docker 容器 `kaixinyuan` 内完成。宿主机 `~/workspace/kaixinyuan/` 挂载为容器内的 `/home/ra4ing/workspace/`，所以下文命令里的容器内路径可以和宿主机路径一一对应。

---

## 3. 统一的三段式工作流

尽管两个 harness 的实现差异很大，它们对外暴露的使用方式是统一的：

```
.litmus 源文件
      │
      │   ① generate：litmus7 翻译 → C 源码
      ▼
C 测试代码 + utils.c + litmus_io.c + ...
      │
      │   ② compile：GCC 交叉编译 + harness 胶水层 → 裸机 ELF
      ▼
<test>.elf
      │
      │   ③ run：模拟器加载执行 → 内存序观测结果
      ▼
Observation <test> Never/Sometimes/Always  <pos>  <neg>
```

无论你用的是 Spike 还是 NEMU，一次完整的 `make run` 都会把上面三步串起来跑完。区别只在第二步的工具链选择和第三步的模拟器调用。

**generate 阶段**使用 `litmus7 -mach riscv -mode presi -stdio false -avail 2` 把 `.litmus` 翻译成 C。`-mode presi`（pre-silicon）是关键：它会让 `litmus7` 用用户态 barrier（基于 `fence` 指令和自旋计数器）来同步各个 worker，而不是用 pthread barrier——这是 harness 能在裸机上立住的前提。`-stdio false` 让生成代码走 `emit_string`/`emit_int`，而不是 `printf`，因为我们的 syscalls 桩只会实现最基本的字符输出。

**compile 阶段**用 `riscv64-...-gcc` 把 litmus7 的生成代码和 harness 的 `.c`/`.S` 一起编成裸机 ELF。两个项目在这里的工具链选择不同，但都以 `-static -ffreestanding -mcmodel=medany` 为基调，并通过 `-Wl,--allow-multiple-definition` 让 harness 的 `launch` / `join` / `mmap_exec` 覆盖 `utils.c` 里基于 pthread 的同名函数。

**run 阶段**就是把 ELF（或 flat binary）喂给对应的模拟器。Spike 会按 `-p(AVAIL+1)` 同时跑起多个 hart；NEMU 则在单 hart 进程里靠协作式纤程依次推进。最终产物都是相同格式的 litmus 输出：Histogram、Witnesses、Observation。

---

## 4. Spike Harness：多 hart 裸机方案

Spike 是 RISC-V 官方模拟器，它本身就支持 `-p N` 启动 N 个 hart，并且所有 hart 从同一个 `_start` 入口开始并行执行。这个特性给了 Spike harness 一条很自然的路：**真的用多个 hart 来跑 worker**，hart 0 当 orchestrator 调 `main()`，hart 1..AVAIL 当 worker 运行 `zyva()`。所以对 `AVAIL=2`，Spike 要用 `-p3`：1 个 main + 2 个 worker。

### 4.1 线程替换：`_litmus_slots` 共享内存通道

裸机下没有线程调度器，但 Spike 已经帮我们把“多个独立执行流”这件事做好了——所有 hart 同时跑。`launch()` / `join()` 的任务就简化成：在 hart 0 和 secondary hart 之间开一条共享内存通道。

我们用一个全局数组 `litmus_slot_t _litmus_slots[8]`，每个 slot 32 字节对齐（避开 false sharing），里面放三样东西：要跑的函数指针 `fn`、参数 `arg`、完成标志 `done`。所有 secondary hart 在 `startup.S` 里被丢进一个自旋循环，反复 fence + 读 `slot->fn`；一旦非空就跳转执行，执行完把 `done=1`，继续自旋。`launch()` 往下一个空闲 slot 写入 `fn`/`arg`，`join()` 自旋等 `done=1`。

这里踩过一个很典型的坑：最初用 `t1` 寄存器在 secondary hart 的 spin loop 里保存 slot 指针，结果 `jalr` 调用 `zyva()` 返回后，`t1` 作为 caller-saved 寄存器被函数内部覆盖了，`done=1` 写到了错误的地址。改用 callee-saved 的 `s1` 之后才修复。文档 [`spike-litmus-harness/docs/DESIGN.md`](spike-litmus-harness/docs/DESIGN.md#startups--裸机多-hart-入口) 里把这段 rationale 写得很清楚。

### 4.2 libc 与 I/O：HTIF + newlib

Spike 用 HTIF（Host-Target Interface）作为 target 和 host 之间的通道：内存里有 `tohost` / `fromhost` 两个 64 位字，写 `tohost` 就能让 Spike 主循环帮你打印字符或退出程序。我们在 [`syscalls.c`](spike-litmus-harness/syscalls.c) 里实现了一小组 newlib 需要的 `_write` / `_sbrk` / `_exit` / `_fstat` / `_gettimeofday` 桩，底下全部映射到 HTIF。

`htif_putchar` 采用 fire-and-forget 策略：只等前一个字符被 Spike 取走（`tohost` 清零），就写入下一个，不等 host 的 ACK。这避免了最初版本里 `htif_putchar` 死锁的问题。

编译器方面，Spike harness 用的是 Ubuntu 自带的 `riscv64-linux-gnu-gcc`，而不是自编译的 `riscv64-unknown-elf-gcc`。原因很朴素：自编译的 unknown-elf 工具链只完成了 stage1，缺了 `libgcc.a`，而 `litmus7` 生成代码会用到 `__extenddftf2` 之类的软浮点符号。Ubuntu 包里 `libgcc.a` 是完整的，拿过来和自编译的 newlib sysroot 一搭配，就能同时满足“有软浮点”和“能裸机链接”这两个需求。

### 4.3 快速上手

所有命令都在容器里执行。一条命令跑完整个流程：

```bash
docker exec kaixinyuan make -C /home/ra4ing/workspace/spike-litmus-harness \
    LITMUS=/home/ra4ing/workspace/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
    AVAIL=2 NRUNS=2 SIZE=20 run
```

参数含义：`LITMUS` 是测试文件路径（必填）；`AVAIL` 是 worker 数量（默认 2），Spike 实际会启 `AVAIL+1` 个 hart；`NRUNS` 是外层迭代次数，`SIZE` 是每轮内部循环大小。也可以走便捷脚本 [`run_litmus.sh`](spike-litmus-harness/run_litmus.sh)。更详细的参数、常用命令和输出解读见 [`spike-litmus-harness/docs/MANUAL.md`](spike-litmus-harness/docs/MANUAL.md)。

---

## 5. NEMU Harness：单 hart + 协作式纤程调度

NEMU 的设计原则和 Spike 不同。它的内存路径使用 `MAP_PRIVATE | MAP_ANONYMOUS` 分配（见 `nemu/src/memory/paddr.c:186-195`），每个 NEMU 进程都是私有地址空间；要多 hart 只能靠 `-p N` 启多个进程。退出机制不是 HTIF 而是 `nemu_trap` 伪指令（`.word 0x0000006b`，退出码在 `a0`），控制台不是 HTIF 而是 UART16550 MMIO（地址 `0x310b0000`）。这些事实在进入开发之前就通过 [`PROBE_RESULTS.md`](nemu-litmus-harness/PROBE_RESULTS.md) 做了完整探针。

更关键的约束是：**不能改 NEMU 源码**。这意味着 Spike 版里那套“多个真·hart 同时跑”的方案不能照抄，也不能靠 `MAP_SHARED` 在多个 NEMU 进程间共享内存做同步，因为 NEMU 走的是私有映射。

### 5.1 核心问题：Barrier 死锁

`litmus7` 生成的 `barrier_wait()` 本质上是一段自旋：原子递增到达计数，然后 `while (p->sense == sense)` 等所有线程到齐。Spike 下这没问题，因为 hart 真的在并行；但在 NEMU 里，如果你按顺序 `launch` 两个 worker，第一个 worker 一进入 barrier 自旋就再也不让出 CPU，第二个 worker 永远没机会运行——整个测试会 hang 死。

我们没有办法在裸机上搞抢占式调度（没有可靠的定时器中断路径），也没办法改 `litmus7` 生成代码里的 `static barrier_wait()`（它是生成产物，不好稳定维护）。于是 NEMU 版引入了一层 Spike 版没有的东西：**协作式纤程调度器**。

### 5.2 Fiber 调度器的构造

[`fiber.S`](nemu-litmus-harness/fiber.S) 做真正的上下文切换：保存/恢复 `s0`–`s11`、`ra`、`sp` 共 14 个寄存器，每个 fiber 栈 64KB。[`nemu_hart.c`](nemu-litmus-harness/nemu_hart.c) 把 `launch()` 和 `join()` 的语义改写为 fiber 风格：`launch()` 只创建 fiber，不立即执行；`join()` 驱动调度循环 `fiber_run_until(id)`，直到目标 fiber 完成为止。`pthread_t` 被直接定义成 `unsigned long`，承载 fiber id。

剩下的问题是：**在哪里插入 `fiber_yield()`？** 如果完全不让出，调度器就和没有一样；但我们又不能改动 barrier 的自旋代码。答案是借一个现成的拦截点——`__sync_add_and_fetch`。`litmus7` 的 barrier 无论如何都会调用它做原子累加，而它又可以通过宏重定义拦截：

```c
#define __sync_add_and_fetch(ptr, val) \
    harness_sync_add_and_fetch((volatile int *)(ptr), (int)(val))
```

[`harness_barrier.c`](nemu-litmus-harness/harness_barrier.c) 里的实现是：做完原子加之后，如果返回值不为 0（说明我不是最后一个到达 barrier 的，得等别人），就主动 `fiber_yield()`。于是：第一个到达者让出 → 调度器切到第二个 → 第二个完成原子加返回 0，继续往下翻转 sense → 第一个被唤醒，sense 已经变了，退出等待。死锁就这样被拆掉了。

这个设计的妙处在于，它在不改 `litmus7` 生成代码、也不改 NEMU 源码的前提下，把协作式调度"偷偷"塞进了 barrier 语义里。代价是：NEMU 版里的“多线程”本质上是串行交错执行的 fiber，不是真并行。但只要目标是观察 `litmus` 的 Observation 结果，这个代价完全可以接受。

### 5.3 退出与 I/O：适配 NEMU 约定

和 Spike 最大的不同在这三处：

- **退出**用 `nemu_trap`：`_exit(code)` 的实现是 `a0 = code` 然后发射 `.word 0x0000006b`。NEMU 主循环看到这条伪指令就会把它当作程序结束点。
- **控制台**往 `0x310b0000` 写字节即可，对应 UART16550 的 THR 寄存器。`_write` 逐字节写过去就行。
- **编译器**用的是 `riscv64-unknown-elf-gcc + picolibc`，更贴近裸机交叉编译场景；链接基址仍为 `0x80000000`，和 NEMU 默认 `CONFIG_MBASE` 对齐。

### 5.4 快速上手

典型命令：

```bash
make -C /home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness \
  LITMUS=/home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
  NEMU=/home/ra4ing/workspace/kaixinyuan/nemu/build/riscv64-nemu-interpreter \
  run
```

需要注意，NEMU 二进制运行时依赖 `libsdl2-2.0-0`，在精简镜像里容易漏装；完整的依赖和一键安装命令见 [`nemu-litmus-harness/docs/MANUAL.md`](nemu-litmus-harness/docs/MANUAL.md)。参数 `AVAIL` 在 NEMU 版里控制的其实是纤程数量而非硬件 SMP 的 hart 数，但对外暴露的语义保持一致。

---

## 6. 两个 Harness 的对照

把上面讲的东西压成一张表便于快速回忆：

| 维度 | spike-litmus-harness | nemu-litmus-harness |
|---|---|---|
| 并发模型 | 真正的多 hart 并行（`-p(AVAIL+1)`） | 单 hart 进程 + 协作式纤程 |
| 线程 launch/join | `_litmus_slots[]` 共享内存 + secondary hart spin | `fiber_create` / `fiber_run_until` |
| Barrier 同步 | 靠 hart 真并行，无需额外改造 | `__sync_add_and_fetch` 宏拦截 + `fiber_yield()` |
| 退出机制 | HTIF：`tohost = (code<<1) \| 1` | `nemu_trap`：`.word 0x0000006b`，`a0` 为退出码 |
| 控制台 | HTIF：`tohost` 编码 device=1/cmd=1/ch | UART16550 MMIO：写 `0x310b0000` |
| 编译器 | `riscv64-linux-gnu-gcc` + newlib sysroot | `riscv64-unknown-elf-gcc` + picolibc |
| 可执行内存 | `malloc` 替代 `mmap(PROT_EXEC)` | bump allocator 替代 `mmap` |
| 目标产物 | ELF（Spike 直接吃） | flat `.bin`（NEMU 走 `-b`） |
| 内存基址 | `0x80000000` | `0x80000000` |
| 入口 hart 区分 | `csrr a0, mhartid`，hart 0 跑 main | 同上，但 secondary 实际由纤程承担 |

两者共享的部分其实比看上去多：`litmus7` 命令、`-mode presi`、`fence rw,rw` 的 `mbar()`、`affinity_stub.c`、`pthread.h` 类型定义、链接脚本的整体结构、乃至“harness 的 `launch/join` 通过 `--allow-multiple-definition` 覆盖 `utils.c`”这一招，都是共用的。真正分叉发生在两个位置：**怎么让多个执行流推进起来**（多 hart vs. 纤程），以及**怎么和模拟器谈退出和 I/O**（HTIF vs. `nemu_trap` + UART）。

---

## 7. 结果与 verdict 解读

以 `LB-mixed1.litmus` 为例，两边跑出的典型输出都是：

```
Test LB+mixed1 Allowed
Histogram (2 states)
20    :>0:x5=1; 1:x1=0; 1:x5=0; 1:x9=1; 1:x10=0;
20    :>0:x5=0; 1:x1=0; 1:x5=1; 1:x9=1; 1:x10=0;
No

Witnesses
Positive: 0, Negative: 40
Condition exists (0:x5=1 /\ 1:x1=0 /\ 1:x5=1 /\ 1:x9=1 /\ 1:x10=0) is NOT validated
Observation LB+mixed1 Never 0 40
```

解读顺序：`Histogram` 把所有观测到的最终状态按出现次数列出来，`Witnesses` 行统计了满足（Positive）和不满足（Negative）`exists` 条件的次数，`Observation` 是最终的 verdict——`Never` 表示该条件从未被观测到，`Sometimes` 表示偶尔观测到，`Always` 表示总是被观测到。

NEMU 版输出末尾还会附带一段 NEMU 内部日志，像 `HIT GOOD TRAP at pc = 0x...` 和 `NEMU exit with good state`，这是模拟器正常退出时的标志信息，不是 harness 额外打印的。如果看到 `HIT CRITICAL ERROR: trap when mnstatus.nmie close`，这是 `nemu_trap` 退出流程里的 benign 警告，后面仍然会跟 `HIT GOOD TRAP`，不影响测试结论。

---

## 8. 延伸阅读

- [`PROGRESS.md`](PROGRESS.md)：Spike 版开发期的进度笔记，记录了最初的目标拆解、已修复的关键 bug，以及具体的文件布局。
- [`spike-litmus-harness/docs/DESIGN.md`](spike-litmus-harness/docs/DESIGN.md)：Spike 版的完整设计文档，包含 `startup.S` 的逐行解释、HTIF 协议细节、链接脚本的内存布局。
- [`spike-litmus-harness/docs/MANUAL.md`](spike-litmus-harness/docs/MANUAL.md)：Spike 版的使用手册，包含所有 Makefile 目标、参数、常用命令和路径映射。
- [`nemu-litmus-harness/docs/DESIGN.md`](nemu-litmus-harness/docs/DESIGN.md)：NEMU 版的完整设计文档，重点讲协作式纤程调度器、`__sync_add_and_fetch` 注入、以及和 Spike 版的每一处分叉。
- [`nemu-litmus-harness/docs/MANUAL.md`](nemu-litmus-harness/docs/MANUAL.md)：NEMU 版的使用手册，包含完整依赖清单（注意 `libsdl2-2.0-0`）和常见问题。
- [`nemu-litmus-harness/PROBE_RESULTS.md`](nemu-litmus-harness/PROBE_RESULTS.md)：开工前对 NEMU 接口（`mhartid`、`nemu_trap`、UART16550、AMO/fence）做的探针结论。如果未来 NEMU 的这些接口发生变化，第一步就是重跑这份探针。
