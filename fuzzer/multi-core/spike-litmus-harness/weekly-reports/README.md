# 第 1 周：bare-metal harness 设计与首次编译

- 分析 litmus7 生成的 C 代码对 POSIX 的依赖：pthreads、stdio、mmap、affinity，确定需要替换的接口
- 设计裸机多 hart 启动方案：hart 0 跑 main + 清 BSS，其余 hart 自旋等待任务分发
- 设计 launch/join 机制：共享内存 slot 数组 + fence 同步，替代 pthread_create/join
- 实现 HTIF 输出桩：通过 spike 的 tohost/fromhost 寄存器做字符输出和程序退出
- 编写 linker script 和 Makefile 编排（litmus7 生成 → GCC 编译 → spike 运行）
- 首次编译成功，spike 输出 litmus 测试 header 后挂死

# 第 2 周：多 hart 调试

- **问题**：测试 header 能打印，但 `join()` 永远等不到 worker 完成
- 排查发现多个 bug 逐个修复：
  - `htif_putchar` 与 spike 的 HTIF 主循环形成互锁 → 改为非阻塞写入
  - `main(0, NULL)` 导致命令行解析空指针崩溃 → 构造合法 argc/argv
  - secondary hart 全局指针 `gp` 未初始化，地址计算错误 → 启动时加载 `__global_pointer$`
  - spike 需要 AVAIL+1 个 hart（1 个协调线程 + N 个工作线程）
  - **根因**：secondary hart 用 caller-saved 寄存器 `t1` 保存 slot 指针，调用 worker 函数后被覆盖，完成标记写到错误地址 → 改用 callee-saved `s1`
- 首次看到完整输出：`Observation LB+mixed1 Never 0 40` ✅

# 第 3 周：litmus7 版本适配与文档

- **问题**：容器内 litmus7 版本与之前不同，生成的文件结构有差异（`run.c`/`topology.c` 被内联，`toh.sh` 不再自动生成）
- 更新 Makefile 适配新版 litmus7 的输出结构
- 编写使用手册和技术文档（问题背景、三层流程、胶水层设计原理、关键设计决策）
- 清理工作区，端到端验证通过
