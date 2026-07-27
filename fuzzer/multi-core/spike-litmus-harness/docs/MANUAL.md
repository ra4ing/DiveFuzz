# spike-litmus-harness 使用手册

## 前置条件

Docker 容器 `kaixinyuan` 处于运行状态。

## 一条命令运行测试

```bash
docker exec kaixinyuan make -C /home/ra4ing/workspace/spike-litmus-harness \
    LITMUS=/home/ra4ing/workspace/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
    run
```

这会自动完成：litmus7 生成 C 代码 → 编译为裸机 ELF → spike 运行并输出结果。

## 参数说明

| 参数 | 默认值 | 含义 |
|---|---|---|
| `LITMUS` | *(必填)* | `.litmus` 测试文件的容器内路径 |
| `AVAIL` | `2` | 并发 worker 线程数（spike 会用 `AVAIL+1` 个 hart） |
| `NRUNS` | `2` | 外层循环次数（`NUMBER_OF_RUN`） |
| `SIZE` | `20` | 每轮内部迭代次数（`SIZE_OF_TEST`） |

## 常用命令

```bash
# 只编译不运行
docker exec kaixinyuan make -C /home/ra4ing/workspace/spike-litmus-harness \
    LITMUS=/home/ra4ing/workspace/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
    compile

# 增大测试规模（100 轮 × 每轮 1000 次）
docker exec kaixinyuan make -C /home/ra4ing/workspace/spike-litmus-harness \
    LITMUS=/home/ra4ing/workspace/litmus-tests-riscv/tests/mixed-size/HAND/LB-mixed1.litmus \
    AVAIL=2 NRUNS=100 SIZE=1000 run

# 清理构建产物
docker exec kaixinyuan make -C /home/ra4ing/workspace/spike-litmus-harness clean

# 手动运行 ELF（不经过 Makefile）
docker exec kaixinyuan /home/ra4ing/workspace/riscv/bin/spike -p3 \
    /home/ra4ing/workspace/spike-litmus-harness/build/LB-mixed1/LB-mixed1.elf

# 列出可用的 litmus 测试
docker exec kaixinyuan find /home/ra4ing/workspace/litmus-tests-riscv -name "*.litmus" | head -20
```

## 输出解读

一次成功运行的输出长这样：

```
make LITMUS=LB-mixed1.litmus run      
=== Running LB-mixed1 on spike (3 harts: 1 main + 2       workers) ===
timeout 300 /home/ra4ing/workspace/riscv/bin/spike -p3 build/LB-mixed1/LB-mixed1.elf || [ $? -eq 124 ] && echo "[spike timed out after 300s — test results above are complete]"
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
```

- `Histogram`：观测到的每个执行路径及其出现次数
- `Positive` / `Negative`：满足/不满足 `exists` 条件的次数
- `Observation`：`Never` = 条件从未满足；`Sometimes` = 偶尔满足；`Always` = 总是满足

## 路径映射

宿主机 `/home/ra4ing/workspace/kaixinyuan/` 挂载为容器内 `/home/ra4ing/workspace/`。因此：

| 宿主机路径 | 容器内路径 |
|---|---|
| `.../kaixinyuan/spike-litmus-harness/` | `/home/ra4ing/workspace/spike-litmus-harness/` |
| `.../kaixinyuan/riscv/bin/spike` | `/home/ra4ing/workspace/riscv/bin/spike` |
| `.../kaixinyuan/litmus-tests-riscv/` | `/home/ra4ing/workspace/litmus-tests-riscv/` |
