# DiveFuzz-MC

DiveFuzz-MC 是 DiveFuzz 的多核扩展，用**对形式化内存模型差分**的方式 fuzz RISC-V 多核处理器：生成多 hart 内存序测试，用 herd7 求解 RVWMO 允许的结果集，在 DUT 上重复运行，凡出现允许集之外的观测即为候选 bug。后端是 litmus7，oracle 是 herd7。

DiveFuzz-MC 覆盖 37 个测试族——litmus-tests-riscv 的全部经典拓扑原型（2 线程六环 MP/SB/LB/S/R/2+2W、同址相干 CoRR/CoRW/CoWR/CoWW、多线程因果 WRC/RWC/IRIW/ISA2/3.LB/3.SB/3.2W/WWC/WRW/WRR/Z6.0–Z6.5/RDW/RSW/IRWIW/IRRWIW、原子 AMO/LRSC/MPAcqRel、依赖 LBdep/LBadc，hart 2/3/4）与 9 条可组合的随机化轴（`--randomize` 开寄存器/存值/fence 位/同字别名/宽度混用/AMO 操作/aq·rl 位/延迟链长；`--noise-level L1` 叠加指令间 interleaving 噪声）。确定性模式可复现，随机化模式把单个族展开成大量形态各异的变体。3.2W 是全 store 族，观测最终内存；MPAcqRel 用 `amoswap.w.rl`/`lr.w.aq` 压 aq/rl 序位实现。

## 去哪读什么

想理解系统怎么工作、随机化为什么安全、有哪些已知约束——读 **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**。它讲清数据模型（modeled window 是唯一的语义边界）、GenCtx 的"形状与细节分离"设计、每条轴的 soundness 论证；末尾「代码架构」一节给出每条轴的**精确代码落点**（生成→渲染→校验三角）、耦合分析（唯一隐式契约是 `noise.SCRATCH` 与 `regalloc` 池不相交）与扩展指南。

想装环境、生成种子、在 DUT 上跑、读结果、加族加轴——读 **[docs/USAGE.md](docs/USAGE.md)**。它是操作手册，含两个环境坑、两个入口（CLI 生成 / YAML 闭环）、随机化开关语义、判定结果解读，以及回归压力测试与扩展指南。

两份 litmus harness（spike 的 HTIF 多 hart 方案、nemu 的协作式纤程方案）的逐行设计与使用手册在各自的 `docs/{DESIGN,MANUAL}.md`；根目录的 `README.md` / `PROGRESS.md` 是 harness bring-up 期的实现细节与已修 bug 记录。

## 一句话定位

随机化轴全部集中在 `GenCtx`——加轴只改 `GenCtx`，不碰族定义；allowed 集永远以 herd 对实际发出的 `.litmus` 的求解为准，所以轴怎么组合，比对都成立；唯一约束是发出的构造必须同时被 herd 和汇编器接受。
