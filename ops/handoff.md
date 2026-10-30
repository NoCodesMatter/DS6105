# Sun NengKe：数据库加载与性能测量交接

状态：2026-10-30。数据库契约 1.0.0；五个阶段均完成真实 PostgreSQL 导入和查询检查。

## 已完成

| 阶段 | 数据库 | 累计交易数 | Q5 保留 town 数／该阶段总 town 数 |
|---|---|---:|---:|
| stage1 | sd6105_housing | 37,153 | 9／26 |
| stage2 | sd6105_stage2 | 89,356 | 11／26 |
| stage3 | sd6105_stage3 | 332,311 | 20／26 |
| stage4 | sd6105_stage4 | 619,507 | 4／27 |
| stage5 | sd6105_stage5 | 989,158 | 2／27 |

每个阶段均核对六张表的行数，运行共享数据库校验，确认最后 COMMIT。
Q2 汇总数量在全部阶段与交易表一致；stage4 的 36 条、stage5 的 51 条未知租约记录保留。
逐阶段证据和输入哈希见[阶段清单](manifests/stages.json)及[查询检查](evidence/query_review.json)。

## 给 Lu：正式数据及计数口径

- [Task 3 原始数据](benchmark/results/task3_baseline_01/task3_raw.csv)：**150 条**，每个阶段每个查询五次。
- [Task 4 对比数据](benchmark/results/task4_indexes_02/task4_raw.csv)：**210 条**，包含原 Task 3
  最大阶段的 30 条基线，以及六个索引配置的 **180 条新观测**。其中 30 条基线属于复用，不能算作新实验。
- [独立对照](benchmark/results/task4_indexes_02/control_raw.csv)：**30 条新观测**，仅用于检查环境波动，
  不替换正式 Task 3 基线。总共采集了 **360 条新计时记录**：150 + 180 + 30。
- [基线实验元数据](benchmark/results/task3_baseline_01/manifest.json)和
  [索引实验元数据](benchmark/results/task4_indexes_02/manifest.json)记录查询版本、来源和参数。
- 对应目录中保留各阶段／索引配置的 metadata 与五次计时计划 JSON。`plan_uses_index` 表示该次计划实际使用的候选索引。

测量方法为 `EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)` 的服务器 `Execution Time`，不包含规划和客户端传输。
每个查询先预热一次，再记录五次；work_mem=64MB、jit=off。Task 4 使用专用副本 `sd6105_stage5_indexed`，
原五个基线数据库保持独立。每种索引配置的完整查询结果摘要与无索引对照一致。

## 需要 Lu 在报告中解释的结果

以下均为五次平均值相对**正式 Task 3 最大阶段基线**的变化，不代表统计显著性检验：

| 配置 | 主要观测 | 计划证据 |
|---|---|---|
| sale_month 索引 | Q1：119.328 → 94.033 ms，降低约 21.2% | Q1 使用该索引 |
| flat_id 索引 | Q4：1,631.019 → 3,757.134 ms，增加约 130.4% | Q4 使用该索引；保存计划包含多层 nested loop |
| flat_type/building 索引 | Q3：409.603 → 365.897 ms，降低约 10.7% | Q3 使用该索引；效果仍需结合波动解释 |
| building/distance 索引 | Q4 降低约 11.5%；Q5 降低约 20.4% | Q4、Q5 使用该索引 |
| town 索引 | 六个查询均未使用该候选索引 | 耗时变化不能归因为该索引被使用 |
| 全部五个索引 | Q4 耗时增加约 118.9% | Q4 同时使用 building/distance 和 flat_id 索引 |

独立无索引对照相对正式基线的变化：Q1 +11.3%、Q2 +6.7%、Q3 +8.5%、Q4 +0.2%、
Q5 −4.4%、Q6 −1.7%。这是一轮对照的观测范围，不是统计置信区间或统一噪声阈值。
正式结论、最终保留哪些索引、图表与性能分析由 Lu 综合原始样本和计划确定。

Lu 先前 746,203 条交易、旧视图定义下的 scratch 结果不应直接替代本轮 989,158 条记录的正式结果。

## 给 WU / LI

- WU：数据库均按冻结契约 1.0.0 创建，使用已采用的 nearest-view 改写以及 2,000 m 上限。
- LI：Q1–Q6 在五个阶段均能执行；Q5 的固定 450,000 阈值在全部阶段保留部分 town。
  [查询检查](evidence/query_review.json)记录输出数量；查询截图和业务结论仍由 LI 负责。
- Q1 在 stage1 只有 2015–2016 的可用数据；从 stage2 开始完整覆盖固定 2014–2016 窗口。

## 接下来

1. Lu 用两份正式原始 CSV 生成 Task 3 / Task 4 图表，结合独立对照和计划确定最终索引结论。
2. Lu 将[Sun 的英文报告材料](report.md)并入团队报告；按课程要求声明 AI 辅助使用。
3. WU 做全流程技术验收；LI 完成新版结果截图／业务解释。
4. Sun 检查本模块改动，通过团队的分支与 PR 流程提交，并准备说明加载事务、五阶段来源和测量口径。

文档提供交接内容；本工作流没有自动向组员发送消息。
