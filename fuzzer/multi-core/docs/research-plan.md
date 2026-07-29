# DiveFuzz-MC XiangShan 多核随机测试规划

## 1. 目标

为 XiangShan DUT 生成可判定的多 hart 随机指令流，发现 RVWMO、cache coherence、AMO、LR/SC、fence、aq/rl 相关缺陷。

主判定：`observed outcome ∈ RVWMO/herd allowed outcomes` 为 PASS；否则为 `BUG_MODEL_VIOLATION`。timeout、trap、no outcome、malformed outcome 归档为执行异常。

## 2. 决策与边界

| 项 | 决策 |
|---|---|
| DUT | XiangShan |
| 测试形态 | 类 DiveFuzz 随机多 hart 指令流 |
| 随机边界 | modeled window + 受控随机噪声 |
| 主 oracle | RVWMO/herd model oracle |
| 判定粒度 | outcome-level checking |
| difftest | 仅作 smoke/debug/定位辅助 |
| backend | litmus7 |

首版不做：多核 lockstep difftest、OS/pthread、interrupt/VM/vector 混合、随机特权级切换、随机 MMIO/CSR chaos。

## 3. 总体流程

```text
MC generator -> MCProgram
MCProgram -> .litmus -> herd/RVWMO -> allowed_outcomes.json
MCProgram -> executable -> XiangShan repeated runs -> observed_histogram.json
allowed_outcomes + observed_histogram -> oracle checker -> archive/corpus/reducer
```

## 4. MCProgram

```text
MCProgram(seed_id, isa, hart_count, shared_vars, private_vars,
          hart_programs, observed, oracle_spec, noise_profile, metadata)
HartProgram(prologue_noise, modeled_window, epilogue_noise, result_capture)
```

Modeled events：`Load`、`Store`、`Fence`、`FenceTso`、`AMO`、`LR`、`SC`、`Dependency`、`Delay`。

Model window 包含所有影响 observed outcome 的共享内存事件，必须可导出 `.litmus` 并由 herd/RVWMO 判定。

## 5. 噪声约束

首版允许：nop/delay、整数寄存器计算、私有分支、私有内存 load/store、确定不会 trap 的 XiangShan 支持指令。

首版禁止：访问 modeled shared vars、写 observed registers、写 runtime/result/barrier/tohost、未建模 shared load/store/AMO/LR/SC、未建模 fence/aq/rl、随机 CSR write、随机 MMIO、随机 trap、随机特权级切换。

## 6. 生成器

生成流程：select test family -> choose hart count -> allocate vars -> generate modeled events -> assign regs/values -> insert fence/aq/rl/dependency -> insert private noise -> choose observed state -> validate -> export oracle/DUT input。

首版测试族：SB、LB、MP、IRIW、WRC、RWC、CoRR、CoWR、AMO atomicity/order、LR/SC conflict/success、aq/rl message passing、fence/fence.tso variants。

首版随机维度：hart_count 先 2 后 4；地址关系 same word/same cacheline/different cacheline；操作 mix load/store/fence/AMO/LR/SC/dependency/delay；ordering none/fence/fence.tso/aq/rl/aqrl；noise_level L0/L1/L2。

## 7. Validator

Validator 必须保证 seed 可运行且 oracle sound。不能证明安全的 seed 必须丢弃。

必须检查：每 hart 至少一个 modeled event；observed register 由 modeled Load/AMO/LR/SC 定义；observed memory 属于 shared vars；shared 访问宽度与对齐合法；LR/SC 成对且地址合法；AMO 只在 A 扩展启用时生成；aq/rl 使用位置合法；noise 不污染 shared vars、observed registers、runtime areas；noise 不包含可能 trap 的指令；temp regs 不与 runtime reserved regs 冲突；seed 可导出 litmus 与 DUT executable。

## 8. Oracle 与 Outcome

输入：`seed.litmus`、`observed_histogram.json`。输出：`PASS`、`BUG_MODEL_VIOLATION`、`TIMEOUT`、`RUNTIME_TRAP`、`NO_OUTCOME`、`MALFORMED_OUTCOME`、`INFRA_ERROR`。

关键要求：必须获得完整 allowed outcome 集；普通 `exists` verdict 不能替代 allowed outcomes。

Canonical outcome 使用 JSON，例如 `{"h0.r1":0,"h1.r2":1,"x":1,"y":1}`。litmus7 backend 将 Histogram/Observation 转为 canonical outcome。

## 9. Backend 与 Runner

backend：`MCProgram -> .litmus -> litmus7 -> C -> ELF/bin -> DUT`。

XiangShan runner contract：输入 executable、hart_count、runs_per_seed、timeout/max_cycles、metadata；输出 stdout/stderr、returncode、timeout flag、trap flag、parsed outcome、artifact path。runner 必须支持同一 seed 重复运行并生成 histogram。

## 10. Corpus、归档、Reducer

Interaction signature 字段：hart_count、test_family、event_types、address_relation、fence_profile、aqrl_profile、amo_profile、lrsc_profile、dependency_profile、noise_level、observed_outcome_class。

保留条件：new signature、new observed outcome、rare outcome、`BUG_MODEL_VIOLATION`、`TIMEOUT/TRAP/NO_OUTCOME`。

Bug archive：`seed.mc.json`、`seed.litmus`、`seed.S/elf/img`、`allowed_outcomes.json`、`observed_histogram.json`、`oracle_report.json`、`xiangshan_run_*.log`、`replay.sh`、`metadata.json`。

Reducer 顺序：删 noise -> 删无关 modeled events -> 简化 values -> 简化 dependency -> 简化 fence/aq/rl -> 简化 address layout -> 尝试减少 hart_count -> 降低 runs_per_seed 但保留复现。

## 11. 实施路线

### Phase 0: XiangShan runner contract

交付：runner 接口、XiangShanRunner 原型、重复运行、日志保存、异常分类。验收：给定 executable，可自动运行 XiangShan N 次并保存结果。

### Phase 1: MCProgram + model oracle

交付：MCProgram、SB/LB/MP generator、validator、litmus exporter、allowed outcome 解析。验收：1000 个随机 2-hart tests 可 validate 或被明确拒绝；valid tests 可生成 allowed outcomes。

### Phase 2: XiangShan end-to-end

交付：litmus7-compatible executable backend、XiangShan repeated run、outcome parser、oracle checker、bug archive。验收：固定 SB/LB/MP seeds 可在 XiangShan 重复运行；model violation 可检测并归档。

### Phase 3: 受控随机噪声

交付：Noise L0/L1/L2、寄存器/私有内存分配、noise validator。验收：带噪声 seed 仍保持 oracle sound，XiangShan outcome 可解析。

### Phase 4: Feedback + reducer

交付：interaction signature、corpus keep/discard、bug replay、basic reducer。验收：重复 seed 被过滤，new signature/new outcome 被保留，bug archive 可 replay/reduce。

## 12. 最小验证集合

MCProgram validator smoke；SB/LB/MP fixed model oracle；random 2-hart litmus export；herd allowed outcome canonicalization；XiangShan repeated run；outcome parser；histogram aggregation；artificial forbidden outcome checker；timeout/no outcome classification；2-hart XiangShan end-to-end smoke；Noise L0/L1 oracle-soundness check；existing single-core DiveFuzz path unaffected。

## 13. 首要风险

1. herd/RVWMO allowed outcome 获取方式必须先验证。
2. XiangShan 多核运行入口、hart 数、输出通道必须锁定。
3. 随机噪声污染 oracle 会导致误报。
