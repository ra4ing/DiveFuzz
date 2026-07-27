# nemu-litmus-harness 使用手册

## 前置条件

- Docker 容器 `kaixinyuan` 处于运行状态，或者本地 Ubuntu / Debian 已安装下列依赖：
  - **编译期**：`riscv64-unknown-elf-gcc`、`picolibc-riscv64-unknown-elf`
  - **NEMU 构建期**：`libzstd-dev`、`bison`、`flex`、`libsdl2-dev`
  - **NEMU 运行期（容易漏装）**：`libsdl2-2.0-0`
    - NEMU 二进制链接了 SDL2（用于 VGA / 键盘设备模拟）。如果容器里只装了 `-dev` 构建头文件而没有运行时库，执行 NEMU 会报：
      ```
      error while loading shared libraries: libSDL2-2.0.so.0: cannot open shared object file
      ```
    - 修复：`apt-get install -y libsdl2-2.0-0`（装了 `libsdl2-dev` 一般会自动把运行时库也拉进来，但在一些精简镜像里需要显式安装）
- NEMU 已编译，二进制位于 `/home/ra4ing/workspace/kaixinyuan/nemu/build/riscv64-nemu-interpreter`
- `litmus-tests-riscv` 仓库位于 `/home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/`
- `litmus7` 工具是可选的，如果目标测试已经有预生成文件，且位于 `build/<test>/gen/`，就可以直接复用，不必重新生成

### 一键安装所有依赖（容器内 root）

```bash
apt-get update && apt-get install -y \
  gcc-riscv64-unknown-elf picolibc-riscv64-unknown-elf \
  libzstd-dev bison flex libsdl2-dev libsdl2-2.0-0
```

## 一条命令运行测试

```bash
make -C /home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness \
  LITMUS=/home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
  NEMU=/home/ra4ing/workspace/kaixinyuan/nemu/build/riscv64-nemu-interpreter \
  run
```

这会自动完成：生成 C 代码，编译成裸机 ELF，再转换成 NEMU 可执行的二进制并运行。

## 参数说明

| 参数 | 默认值 | 含义 |
|---|---|---|
| `LITMUS` | *(必填)* | `.litmus` 测试文件路径 |
| `NEMU` | `/home/ra4ing/workspace/kaixinyuan/nemu/build/nemu-interpreter` | NEMU 二进制路径 |
| `AVAIL` | `2` | 模拟的 hart 数。NEMU 这里是单 hart 运行，`AVAIL` 实际上控制的是协作式 fiber 数，不是硬件 SMP |
| `NRUNS` | `2` | 测试重复次数 |
| `SIZE` | `20` | 每轮测试规模，对应生成代码里的 `SIZE_OF_TEST` |

## 常用命令

```bash
# 只编译，不运行
make -C /home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness \
  LITMUS=/home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
  compile

# 编译并运行
make -C /home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness \
  LITMUS=/home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
  NEMU=/home/ra4ing/workspace/kaixinyuan/nemu/build/riscv64-nemu-interpreter \
  run

# 清理构建产物
make -C /home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness clean

# 构建 NEMU（只在首次配置时需要）
make -C /home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness build-nemu

# 列出可用的 litmus 测试
ls /home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/tests/mixed-size/HAND/*.litmus
```

## 输出解读

一次成功运行的输出长这样：

```
Test LB+mixed1 Allowed
Histogram (2 states)
20    :>0:x5=1; 1:x1=0; 1:x5=0; 1:x9=1; 1:x10=0;
20    :>0:x5=0; 1:x1=0; 1:x5=1; 1:x9=1; 1:x10=0;
No

Witnesses
Positive: 0, Negative: 40
Condition exists (0:x5=1 /\ 1:x1=0 /\ 1:x5=1 /\ 1:x9=1 /\ 1:x10=0) is NOT validated
Hash=79a8c230a2b40f02ef6ab9d1dd206a3c
Observation LB+mixed1 Never 0 40
Time LB+mixed1 ...
[src/cpu/cpu-exec.c:943,cpu_exec] nemu: HIT GOOD TRAP at pc = 0x0000000000000000
[src/utils/state.c:30,is_exit_status_bad] NEMU exit with good state: 2, halt ret: 0
```

- `Test LB+mixed1 Allowed` 表示测试名称和允许关系
- `Histogram (2 states)` 表示最终观测到了 2 种结果状态
- 第一行和第二行各出现 20 次，说明这两个最终状态都被看到了
- `Positive: 0, Negative: 40` 表示 40 次运行里，没有命中被禁止的状态
- `Condition ... is NOT validated` 表示 `exists` 条件没有被验证成立，也就是没有观察到禁态
- `Observation LB+mixed1 Never 0 40` 的结论是 `Never`
- `HIT GOOD TRAP` 表示 NEMU 正常退出，测试结束
- 带有 `[src/...]` 前缀的行是 NEMU 内部日志，不是 harness 自己额外打印的内容
- `HIT CRITICAL ERROR: trap when mnstatus.nmie close` 如果在退出阶段出现，这是 `nemu_trap` 退出流程里的 benign 警告，不是 harness 问题，随后仍然会看到 `HIT GOOD TRAP` 和 `NEMU exit with good state`

## 路径映射

宿主机工作区和容器内路径都以 `/home/ra4ing/workspace/kaixinyuan/` 为根，因此常见路径如下：

| 宿主机路径 | 容器内路径 |
|---|---|
| `/home/ra4ing/workspace/kaixinyuan/` | `/home/ra4ing/workspace/kaixinyuan/` |
| `/home/ra4ing/workspace/kaixinyuan/nemu/build/riscv64-nemu-interpreter` | `/home/ra4ing/workspace/kaixinyuan/nemu/build/riscv64-nemu-interpreter` |
| `/home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness/` | `/home/ra4ing/workspace/kaixinyuan/nemu-litmus-harness/` |
| `/home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/tests/` | `/home/ra4ing/workspace/kaixinyuan/litmus-tests-riscv/tests/` |
