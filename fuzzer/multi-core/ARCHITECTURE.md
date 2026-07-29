# DiveFuzz-MC 架构

本文解释 DiveFuzz-MC 多核模糊测试的设计：它解决什么问题、数据怎么流动、随机化如何嵌入、以及为什么这样设计是正确的。读完本文应能理解整套系统的运作机理，并知道改动落在哪里。

## 问题与方法

RISC-V 多核处理器的内存子系统（load/store queue、store buffer、cache coherence、MSH）是 bug 高发区，而这些 bug 的表现形式是**内存序异常**：两个核的访存交错产生了一个 RVWMO 内存模型不允许的结果。这类 bug 无法用传统的单 trace 差分测试发现——差分测试需要一个"标准答案 trace"，但内存重排是一个**合法行为集合**，不是单条轨迹。

DiveFuzz-MC 的核心 trick 是**对形式化内存模型做差分**：生成一段多 hart 汇编测试，用 herd7 求解"RVWMO 允许的所有最终结果"（allowed 集），在 DUT 上把这段测试重复跑很多次收集实际观测结果，凡出现 allowed 集之外的观测即为候选 bug。herd7 扮演"标准答案"，但它给的是整个合法集合，正好匹配内存重排问题的形状。

## 数据流：从一个族到一个可判定的 seed

生成侧取一个测试族加一个 seed id，产出一个**自洽的 seed**——它随身携带自己的 oracle，因此可以脱离生成环境独立判定。具体流转：`build_program` 选族并填入所有随机化细节，得到一个 `MCProgram`；`litmus_exporter` 把它渲染成 RISCV `.litmus` 文本；`herd_oracle` 把 `.litmus` 喂给 herd7，解析其 `States N` 块得到 `allowed_outcomes.json`；`litmus_backend` 调 `spike-litmus-harness` 的 Makefile，由 litmus7 把 `.litmus` 翻译成 C、再由 `riscv64-linux-gnu-gcc` 链接成裸机 ELF。执行侧的 runner 把 ELF 喂给 DUT、PTY 流式采集输出、检测到 litmus 的 `Observation` 完成标记即终止，`outcome` 解析直方图，最后 `oracle.classify_outcomes` 把观测结果与 allowed 集比对。

判定优先级是 **trap > 直方图 > 超时 > 无结果**。这个顺序是为了适应 spike 这类模拟器"跑完测试后挂起不退出"的行为：只要直方图已经打印，即使进程随后被超时杀掉，也按直方图判定，而非误判为超时。

## 数据模型：modeled window 是唯一的语义边界

`MCProgram` 由若干 `HartProgram` 组成，每个 hart 持有一个 `modeled_window`——一串 `ModeledEvent`（Load/Store/Fence/FenceTso），外加前导/夹层/尾部噪声（字符串指令列表）。**整个系统正确性的根基就是这条边界**：herd7 只对 modeled window 求解 allowed 集；window 之外的噪声指令对 oracle 完全不可见。这意味着只要噪声不触碰 window 用到的寄存器与内存，它无论插在哪里都是安全的——这是 L1 interleaving 噪声（见下）能成立的全部理由。

`observed` 是一组"观测寄存器"——某些 load 的目的寄存器，它们的最终值构成测试的 outcome。allowed 集与观测直方图使用同一套键（`h{hart}.{reg}`，原始寄存器名而非逻辑别名），这样比对时无需发明别名映射。一条规范结果就是 `state.items()` 排序后的元组，可哈希、可 JSON 序列化。

## 族：固定拓扑，而非参数化模板

当前 catalog 有七个族，每个是一条**固定的多 hart 拓扑**：

| 族 | hart | 拓扑要点 | 主要压测目标 |
|---|---|---|---|
| SB / LB | 2 | 两个核各做一次 store+load / load+store | 访存重排（store/load buffering） |
| MP | 2 | P0 存两值中间夹 fence，P1 读两值 | release fence 的消息传递保证 |
| MPTSO | 2 | MP 的 fence 换成 fence.tso | store-store + load-store 序 |
| CoRR | 2 | 一个核写一次，另一个核对同地址读两次 | 同地址 coherence（禁止 new→old） |
| WRC | 3 | 写→读→写的因果链跨三核传递 | coherence 因果传递 |
| IRIW | 4 | 两个写者 + 两个独立读者 | 独立写的可见序一致性 |

hart 数是族的**固有属性**，不是全局旋钮。SB 定义上就是 2-hart 拓扑，IRIW 定义上就是 4-hart——"5 hart 的 SB"是另一个测试。因此 `--hart-count N` 是一个**过滤器**：只挑选拓扑要求 N hart 的族，而不是把 N 强加到所有族上。族选择本身是确定性轮换 `test_families[(seed_id - offset) % len]`，保证覆盖可复现。

## GenCtx：形状与细节的分离

这是整套随机化设计的核心。一个族固定了测试的**形状**（哪些 hart、以什么顺序、访问哪些变量），而所有**具体取值**——用哪些物理寄存器、存什么数值、fence 用什么位组合、访问多宽、变量是否别名——全部委托给 `GenCtx`。族 builder 从不直接读取任何随机化开关，它们只向 ctx 索取：`ctx.alloc` 要寄存器、`ctx.store_value` 要存值、`ctx.fence` 要屏障、`ctx.access_width` 要宽度、`ctx.alias_map` 要别名映射。

这带来一个关键工程性质：**新增一条随机化轴 = 给 GenCtx 加一个方法，不触碰任何族定义**。本轮新加的五条轴都是这么落地的。有些轴（别名、宽度）甚至在 `build_program` 里 post-build 应用——族 builder 完全无感。

各轴做了什么、为什么安全：

**寄存器分配**。`RegAllocator` 按角色（地址/值/观测/scratch）从互不相交的寄存器池里分配。重命名对内存模型是一个双射——herd 在重命名后的 litmus 上重算 allowed 集，runner 观测同样的重命名键。因此这是构造上安全的，且扰动 renamer/ROB/物理寄存器压力。

**存值**。存一个 `[1,127]` 的小立即数。所有 catalog 族都是 value-insensitive 的（语义谓词关心的是可见性/顺序，不是数值大小），所以换值不改变 allowed 集的拓扑。这个上界同时满足 `ori` 的 12 位立即数范围和任何访问宽度。

**fence pred/succ**。屏障的前驱/后继位从 `{r,w,rw}` 独立抽取。这是一条**语义轴**——它确实改变了 allowed 集（比如 `fence r,r` 不强制 store-store 序，被禁止的结果就会变成允许）。但因为 herd 在新 litmus 上重算，比对仍然成立。

**同字别名**。以 0.5 概率把多个逻辑变量坍缩到同一个物理字（`x` 和 `y` 都指向 `x`）。语义轴——herd 看到更少的位置集合，allowed 集随之改变并重算。DUT 则执行真正的同字访问，压 store-forwarding 与同字 coherence。

**访问宽度混用**。每个 Load/Store 事件的宽度独立从 `{1,2,4,8}` 抽取（sb/sh/sw/sd 与 lb/lh/lw/ld）。语义轴——herd 建模子字 coherence，allowed 集重算。存值在 `[1,127]` 保证放得进任何宽度（含 1 字节）。

**L1 噪声（interleaving）**。这是唯一一条"抖动轴"而非"语义轴"。噪声指令只写 scratch 寄存器 `x20`，而 x20 与 modeled window 用到的所有寄存器（地址 x6/x7、值 x12/x13、观测 x10/x11）以及 harness/ABI 保留集都不相交。因此无论噪声插在 prologue、window 事件之间、还是 epilogue，对 window 的访存与观测结果都是零影响——herd 根本看不见它。interleaving（夹在 window 事件之间）是高价值部分：它把 load/store 在时间上拉开，正是压流水线时序、暴露重排敏感 bug 的核心机制。

## 正确性的核心：允许集永远以 herd 对"实际发出的 litmus"的求解为准

理解这套系统的正确性，关键在于认识到 allowed 集**不是一个固定的东西**，而是 herd7 对我们**实际发出的那份 .litmus** 求解的结果。因此一条随机化轴是否安全，只取决于两件事：发出的程序仍是 herd 能建模、且汇编器能编译的东西；观测直方图的键与 allowed 集的键一致。

由此分两类轴。第一类（寄存器重命名、scratch 噪声）**可证明地不改变 allowed 集**——它们对内存模型不可见。第二类（存值、fence 位、别名、宽度）**确实改变** allowed 集，但 herd 在新 litmus 上重算，所以比对仍然有效。唯一的失败模式，是发出了 herd 模型之外或汇编器语法之外的东西。这正是本轮反复印证的纪律：**每引入一种新构造，必须先用 herd7 和真实汇编器双重探针验证**，三者缺一不可。本轮有三种构造没通过这个探针，记录如下。

## 三条受阻的路

**aq/rl 位**。曾尝试给 plain load/store 加 `.aq`/`.rl` 后缀做 acquire/release。herd7 接受（它把注解当建模语义），但真实 RISC-V 汇编器拒绝——plain load/store 的编码里根本没有 aq/rl 位，这些位只存在于 AMO/LR/SC 指令上。所以这条轴要等 AMO/LR-SC 族落地才能解锁；在那之前，plain 访问的 acquire/release 语义只能用 fence 插入来表达（一条未来轴）。

**same-cacheline 布局**。曾想控制变量落在同一缓存行的不同字（间隔 8/16 字节）以压 MSH/存储体冲突。但 litmus7 不支持数组声明（`uint64_t a[2]` 被拒），也不支持指针算术（`x+1` 被拒），所以从 `.litmus` 层面只能表达 same-word 别名（多个寄存器指向同一变量）。same-cacheline-different-word 与跨页需要改 harness 的内存布局代码，是另一个独立的大工程。

**mul 指令**。L1 噪声池原本含 `mul x20,x20,x20`，但 herd7 的 RISC-V litmus 模型不含 M 扩展——这是与 aq/rl 相反的情形：汇编器接受、herd 拒绝。已从 L1 剔除。

## DUT 可移植性

整条 Python 流水线是 DUT 无关的：runner 只是把 `dut_config.cmd` 里的 `$1` 换成 ELF 路径后 shell 执行，PTY 采集 stdout，按 litmus 的 `Observation`/`Histogram` 标记解析。真正与 DUT 耦合的是**裸机 harness 胶水层**（`spike-litmus-harness/`），它实现 HTIF 约定（`tohost`/`fromhost`、加载基址 `0x80000000`）。一个 DUT 可用，当且仅当：能加载裸机 ELF 并在 `0x80000000` 取指；hart 数 ≥ 测试 hart 数 + 1（litmus7 是"控制器 + 工作线程"模型，hart 0 永远是控制器）；输出/退出通道能被 HTIF 桩驱动且落到 PTY 可捕获的 stdout。

spike 原生满足；XiangShan `emu` 与 chipyard（Rocket/BOOM）走标准 HTIF，同一套 harness 预期可用，各需一次 smoke；NEMU 不说 HTIF（退出走 `nemu_trap`、控制台走 UART16550、单 hart per process），需要独立的 `nemu-litmus-harness`（协作式纤程调度，已有）。因此接入一个新的 HTIF DUT，通常只是改一份 `dut_config`（cmd / emu_path / 核数）加一次 smoke。
