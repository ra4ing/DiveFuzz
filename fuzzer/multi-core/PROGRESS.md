# spike-litmus-harness 进度记录

## 目标 ✅ 已达成

将 `litmus-tests-riscv` 中的 `.litmus` 测试文件在 **spike** RISC-V 模拟器上运行，验证内存序（memory ordering）行为。

完整 pipeline：

```
.litmus 文件
    │
    ▼ litmus7（生成 C 代码）
生成的 C 测试代码
    │
    ▼ riscv64-linux-gnu-gcc（交叉编译为裸机 ELF，链接 newlib + libgcc）
bare-metal ELF
    │
    ▼ spike -p(AVAIL+1)（多 hart 模拟执行）
内存序观测结果输出
```

### 验证结果

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

---

## 整体方案

### 核心思路：bare-metal 多 hart harness

`litmus7` 生成的 C 代码依赖 pthreads 和标准 C 库，但 spike 无法运行 Linux 程序。因此需要一套"胶水层"，替换掉所有 OS 依赖：

| litmus7 生成代码依赖 | 我们的替换 |
|---|---|
| `pthread_create` / `pthread_join` | `spike_hart.c` — 用 `_litmus_slots[]` + secondary hart spin loop 替换 |
| `affinity.c`（CPU 亲和性） | `affinity_stub.c` — 空实现 |
| `printf` / `malloc` / `_write` 等 | `syscalls.c` — HTIF tohost/fromhost 桩 |
| `pthread.h` | `pthread.h` — 类型定义（`pthread_t` = `unsigned int`） |
| `sys/mman.h` | `sys/mman.h` — 用 `malloc` 替代 `mmap` |
| `fence` 宏 | `mbar.h` — `fence rw,rw` 内联函数 |
| C runtime 启动 | `startup.S` — 多 hart 裸机入口（hart 0 → main，其余 spin） |
| 链接脚本 | `linker.ld` — 裸机内存布局（.text @ 0x80000000） |

### 编译方案

使用 `riscv64-linux-gnu-gcc`（Ubuntu 交叉编译包，带 libgcc.a）+ 自编译的 newlib sysroot（`riscv/riscv64-unknown-elf/`），以 `-mcmodel=medany -static -ffreestanding` 模式编译。`--allow-multiple-definition` 确保 harness 的 `launch`/`join`/`mmap_exec` 覆盖 litmus7 生成代码中的同名函数。

---

## 文件结构

harness 代码位于 `spike-litmus-harness/`：

```
spike-litmus-harness/
├── Makefile           — 构建编排（generate → .h → compile → run）
├── startup.S          — 多 hart 裸机入口
├── spike_hart.h       — litmus_slot_t 结构体，launch/join 声明
├── spike_hart.c       — launch/join/mmap_exec 实现
├── spike_htif.h       — HTIF 对齐常量
├── syscalls.c         — newlib HTIF 系统调用桩（_write/_exit/_sbrk 等）
├── affinity.h         — cpus_t 类型定义（覆盖 litmus7 生成的版本）
├── affinity_stub.c    — affinity 空实现
├── linker.ld          — 裸机链接脚本
├── mbar.h             — fence rw,rw 内存屏障宏
├── pthread.h          — pthread_t 类型定义
├── run_litmus.sh      — 便捷运行脚本
├── sys/
│   └── mman.h         — mmap/munmap 声明（实际用 malloc 实现）
└── build/             — 构建输出（.gitignore）
    └── <test>/
        ├── gen/       — litmus7 生成的 C 代码
        └── <test>.elf — 编译产物
```

---

## 环境说明

**所有工具均在 Docker 容器 `kaixinyuan` 内运行。**

| 组件 | 容器内路径 | 说明 |
|---|---|---|
| spike | `/home/ra4ing/workspace/riscv/bin/spike` | 自编译（来自 riscv-isa-sim） |
| litmus7 | `/home/ra4ing/.opam/default/bin/litmus7` | opam 安装的 herdtools7 |
| GCC (cross) | `/usr/bin/riscv64-linux-gnu-gcc` | Ubuntu 系统包（带 libgcc.a） |
| libgcc | `/usr/lib/gcc-cross/riscv64-linux-gnu/13/libgcc.a` | GCC 附属，提供软浮点等 |
| newlib sysroot | `/home/ra4ing/workspace/riscv/riscv64-unknown-elf/` | 自编译（来自 riscv-gnu-toolchain） |
| litmus 测试 | `/home/ra4ing/workspace/litmus-tests-riscv/` | 测试用例仓库 |
| Docker 容器 | `kaixinyuan` | Ubuntu 24.04，workspace 已挂载 |

**容器挂载**：宿主机 `/home/ra4ing/workspace/kaixinyuan/` → 容器内 `/home/ra4ing/workspace/`

### 构建源码目录（可按需清理）

以下目录是编译 spike / newlib / riscv-gcc 时用的源码和构建中间产物，编译结果已安装到 `riscv/`，源码目录可以删除以回收空间：

| 目录 | 大小 | 说明 |
|---|---|---|
| `riscv-isa-sim/` | 2.5G | spike 模拟器源码 + 构建产物 |
| `riscv-pk/` | 6.5M | riscv-pk 源码 + 构建产物 |
| `riscv-gnu-toolchain/` | 8.8G | GCC/newlib 工具链源码 + 构建产物 |

删除后可回收 ~11.3GB，保留 `riscv/`（3.2G，编译结果）即可正常工作。

---

## 使用方法

```bash
# 在 Docker 容器内运行
docker exec kaixinyuan make -C /home/ra4ing/workspace/spike-litmus-harness \
    LITMUS=/home/ra4ing/workspace/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
    AVAIL=2 NRUNS=2 SIZE=20 run

# 或使用便捷脚本
docker exec kaixinyuan /home/ra4ing/workspace/spike-litmus-harness/run_litmus.sh \
    /home/ra4ing/workspace/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus 2

# 清理构建产物
docker exec kaixinyuan make -C /home/ra4ing/workspace/spike-litmus-harness clean
```

---

## 已修复的关键 Bug

在开发过程中修复了以下问题：

1. **`LIBGCC` 未定义** — Makefile 加了 `libgcc.a` 路径，修复 `__extenddftf2` 等软浮点缺失符号
2. **Secondary hart `gp` 未初始化** — startup.S 加了 `la gp, __global_pointer$`（带 `.option norelax`）
3. **HTIF `htif_putchar` 死锁** — 改为 fire-and-forget 模式（写 `tohost` 后立即返回，不等 `fromhost` ACK）
4. **`main(0, NULL)` 崩溃 `parse_opt`** — 构造了正确的 `argc=1, argv={"litmus", NULL}`
5. **Spike 需要 `-p(AVAIL+1)` 个 hart** — hart 0 是 orchestrator，hart 1..AVAIL 是 worker
6. **迭代次数控制** — 通过 `sed` 注入 `NUMBER_OF_RUN` 和 `SIZE_OF_TEST`
7. **`t1` 寄存器被 callee 破坏（根因 Bug）** — secondary hart spin loop 用 caller-saved `t1` 保存 slot 指针，`jalr` 调用 zyva() 后 `t1` 被覆盖，`done=1` 写到垃圾地址。改为 callee-saved `s1` 修复
8. **新版 litmus7 输出变化** — `run.c` / `topology.c` 被内联到 `<test>.c`，`toh.sh` 需从 herdtools7 share 目录复制
