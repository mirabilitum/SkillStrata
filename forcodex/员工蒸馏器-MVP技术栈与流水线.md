# 员工蒸馏器 · MVP 技术栈与流水线

> 这份文档承接以下两份设计稿：
> - `员工蒸馏器评估与记录框架.md`
> - `员工蒸馏器-设计文档-v0.2-工程化修订.md`
>
> 目标不是再讲一遍愿景，而是把 MVP 阶段真正要落的技术栈、处理流水线、模块边界和实施顺序写清楚。
> 日期：2026-06-20

---

## 1. 一句话结论

MVP 不做“大而全的自动技能平台”，只做一个针对**程序类、单入口、可重放工具**的蒸馏系统。

技术路线采用：

- `Yunjue-Agent` 的方法学：`reuse-before-create`、回放增强、batch 吸收、warm-start 评估
- GitHub 开源组件做能力底座：`BLAKE3 + datasketch + tree-sitter + ast-grep + embedding + Qdrant`

核心目标只有 3 个：

1. 发现重复或近重复工具
2. 把高质量候选能力沉淀成正式能力
3. 让后续任务减少重复造轮子

---

## 2. MVP 范围

### 2.1 纳入范围

- 程序类工具
- Python 优先
- 单入口脚本 / 明确命令 / 可封装为 MCP tool 的能力
- 有清晰输入输出的格式转换类工具
- 能在隔离环境中重放的能力

### 2.2 暂不纳入

- 提示词沉淀
- 任意长链 workflow 自动拆 DAG
- 团队共享池
- 复杂权限治理
- 多语言统一支持
- 全自动语义合并

### 2.3 推荐起步任务域

优先选一类足够窄、又足够容易出现重复的工具域：

- `pdf -> markdown`
- `docx -> markdown`
- `html -> markdown`

这几类任务的好处是：

- 输入输出清楚
- 容易做 fixture
- 重复工具很多
- 合并关系也容易观察

---

## 3. 设计原则

1. **复现优先**：先证明一个候选能力能被稳定重放。
2. **证据优先**：轨迹、输入输出样本、错误记录比“描述得很好看”更重要。
3. **保守合并**：先做父能力 + 子实现，不强行揉成一个万能工具。
4. **先 exact，后 semantic**：先挡掉明显重复，再做近重和语义检索。
5. **MCP 只负责执行**：检索和注入由宿主适配器控制。
6. **MVP 不追求无人类参与**：关键路径尽量自动，但允许少量 pin / 审核。

---

## 4. 参考外部方法

### 4.1 从 Yunjue-Agent 借什么

MVP 推荐直接借这几条思路：

- `reuse-before-create`
- tool-first，优先沉淀可执行能力
- 使用历史调用日志做回放与增强
- 候选工具与公共工具池分层
- batch 后做吸收/合并，而不是每次即时激进合并
- 用 warm-start 评估能力库的真实价值

### 4.2 不直接照抄什么

MVP 不建议直接照抄这些部分：

- 依赖名字和描述的语义聚类作为主要合并依据
- 研究原型式的宽松执行环境
- 对任意第三方依赖的开放式信任
- 把 benchmark 成绩直接当成内部蒸馏效果

---

## 5. 技术栈

这里分成“推荐主栈”和“可替代项”。

### 5.1 推荐主栈

#### `BLAKE3`

用途：

- 对规范化后的工具定义、代码模板、schema 做指纹
- 抓完全重复的候选项

适合原因：

- 快
- 稳
- 跨平台
- 适合做第一层去重

局限：

- 只能抓 exact duplicate
- 效果强依赖规范化规则

#### `RapidFuzz`

用途：

- 对工具名、短说明、标签做低成本相似度补刀

适合原因：

- 很轻
- 快速
- 对小改字、标点变化、大小写变化很有效

局限：

- 不懂语义
- 误报需要阈值控制

#### `datasketch`

用途：

- 对 README、说明文字、提示词模板、自然语言描述做 MinHash / LSH
- 抓近重复文本

适合原因：

- 比全量 embedding 便宜
- 对局部改写、句子重排比较有用

局限：

- 不擅长真正的语义等价判断

#### `tree-sitter`

用途：

- 把代码解析成 AST
- 为结构归一化和结构搜索提供基础

适合原因：

- 轻
- 快
- 多语言生态成熟

局限：

- grammar 质量依语言而异

#### `ast-grep`

用途：

- 在 AST 层做结构搜索和归一化
- 去掉变量名、字面量、导入顺序这类表面噪声

适合原因：

- 比自己手写 AST visitor 更省工
- 很适合 MVP 阶段快速做结构模板

局限：

- 需要维护规则

#### `FlagEmbedding` 或 `sentence-transformers`

用途：

- 做候选工具描述、签名摘要、示例任务的语义 embedding

适合原因：

- 能补足 hash / MinHash / AST 都抓不到的“语义近似”

局限：

- 模型体积和推理成本更高
- 不是越像越应该合并

#### `Qdrant`

用途：

- 存向量
- 按 payload 做过滤
- 支撑工具检索和相似候选召回

适合原因：

- 单机好落地
- payload 过滤好用
- 很适合“语义检索 + 结构过滤”组合

局限：

- 需要额外维护服务实例

### 5.2 可替代项

- `FAISS`：适合单机实验，但元数据能力弱
- `text-dedup`：适合离线批处理清历史库，不适合在线核心
- `Milvus` / `Weaviate` / `OpenSearch`：太重，不适合 MVP
- `Open-NiCad` / `SourcererCC`：更偏学术 clone detection，接入成本高

### 5.3 最克制的 MVP 组合

推荐采用下面这组：

- `BLAKE3`
- `RapidFuzz`
- `datasketch`
- `tree-sitter`
- `ast-grep`
- `FlagEmbedding` 或 `sentence-transformers`
- `Qdrant`

如果还要再收一刀，第一阶段也可以先去掉 `RapidFuzz`，保留：

- `BLAKE3`
- `datasketch`
- `tree-sitter`
- `ast-grep`
- `embedding`
- `Qdrant`

---

## 6. 系统模块

MVP 建议拆成 6 个模块。

### 6.1 Trace Collector

职责：

- 从宿主 agent 收集原始轨迹
- 保存 tool 调用、命令执行、文件改动、输入输出样本

输入：

- Claude Code hooks / transcript

输出：

- 统一事件
- 原始 artifact

### 6.2 Candidate Extractor

职责：

- 从轨迹中识别候选工具
- 将代码块、脚本、命令封装为候选能力记录

输入：

- 统一 trace

输出：

- `raw` / `candidate` 状态的能力单元

### 6.3 Replay Validator

职责：

- 重放候选能力
- 执行 `Replay Gate` 和 `Output Gate`

输入：

- 候选能力
- fixture
- 执行环境

输出：

- 通过 / 失败
- 错误信息
- 输出快照

### 6.4 Similarity Pipeline

职责：

- 对候选能力做多阶段重复检测
- 输出 exact duplicate、near duplicate、semantic neighbor

输入：

- 候选 manifest
- 代码模板
- 描述文本

输出：

- 相似候选列表
- 相似度证据

### 6.5 Promotion Engine

职责：

- 决定候选能力是继续观察、转正、挂起还是归档

输入：

- 验证结果
- 复用频次
- 相似关系
- 合并建议

输出：

- `candidate`
- `verified`
- `promoted`
- `deprecated`

### 6.6 Retrieval + MCP Service

职责：

- 检索正式能力
- 用 MCP 暴露统一执行入口

输入：

- 任务描述
- 输入类型
- 过滤条件

输出：

- 候选能力列表
- 可调用工具

---

## 7. 多阶段相似性流水线

这部分是 MVP 的核心。

### Stage 0：规范化

先把候选能力整理成统一表示：

- 规范化 manifest
- 标准化输入输出 schema
- 归一化代码模板
- 归一化自然语言描述

没有这一层，后面的 hash 和相似度都不稳。

### Stage 1：Exact Duplicate

工具：

- `BLAKE3`

处理对象：

- 规范化 manifest
- 归一化代码模板
- 参数 schema

目标：

- 挡掉完全重复项

产物：

- `exact_duplicate_of`

### Stage 2：Lexical Similarity

工具：

- `RapidFuzz`
- `datasketch`

处理对象：

- 工具名
- 短说明
- README 片段
- prompt / 使用说明

目标：

- 找出文本层近重复

产物：

- `name_neighbor`
- `text_neighbor`

### Stage 3：Structural Similarity

工具：

- `tree-sitter`
- `ast-grep`

处理对象：

- Python 工具实现

目标：

- 找出“写法不同但结构相近”的工具

处理方式：

- 解析 AST
- 去变量名、常量值、导入顺序等噪声
- 形成结构模板

产物：

- `structure_neighbor`

### Stage 4：Semantic Similarity

工具：

- `embedding`
- `Qdrant`

处理对象：

- 工具描述
- 输入输出契约摘要
- 示例任务

目标：

- 找出“看起来不同，但干的是一类事”的能力

产物：

- `semantic_neighbor`

### Stage 5：Merge Recommendation

输入：

- 上面四层证据
- 验证结果
- 契约兼容性

输出：

- 不合并
- 归到现有父能力
- 建议建立父能力 + 子实现
- 人工 pin 审核

---

## 8. 合并策略

### 8.1 MVP 合并原则

第一版不要做激进的“自动揉成一个通用实现”。

推荐只做两种动作：

1. 标记重复，挂到已有能力名下
2. 创建一个父能力，保留多个子实现

### 8.2 推荐合并结构

示例：

```text
to-markdown
  |- doc-to-md
  |- pdf-to-md
  |- html-to-md
```

这里：

- `to-markdown` 负责统一检索和统一解释
- 子实现保留各自依赖和执行细节

### 8.3 自动合并前提

自动挂靠或合并前，至少满足：

1. `Replay Gate` 通过
2. `Output Gate` 通过
3. 输入输出契约兼容
4. 新样本不会让旧实现失效

不满足时，只做“近邻候选”记录，不自动合并。

---

## 9. 建议的数据结构

### 9.1 Candidate Manifest

```yaml
id: candidate-uuid
name: pdf-to-md
status: candidate
language: python
entry_type: script
entry_ref: ./impl.py
input_schema:
  - pdf_path
output_schema:
  - markdown_text
description: Convert PDF to markdown
normalized_hash: blake3:xxxx
text_minhash: xxxx
structure_hash: xxxx
embedding_ref: qdrant:point-id
source_trace_ids:
  - trace-1
  - trace-2
validation:
  replay_pass: true
  output_pass: false
similarity:
  exact_duplicate_of: null
  structure_neighbors: []
  semantic_neighbors: []
```

### 9.2 Promotion Record

```yaml
candidate_id: candidate-uuid
decision: promoted
reason:
  - replay_pass
  - output_pass
  - reused_3_times
  - merged_under_parent
review_mode: auto
timestamp: 2026-06-20T12:00:00Z
```

### 9.3 Parent Skill Manifest

```yaml
name: to-markdown
status: promoted
kind: parent-skill
children:
  - pdf-to-md
  - docx-to-md
retrieval_tags:
  - markdown
  - convert
  - document
```

---

## 10. 目录结构建议

```text
distiller/
  traces/
  artifacts/
  candidates/
  skills/
  indexes/
  fixtures/
  lineage/
  reports/
```

### 10.1 目录职责

- `traces/`：统一 trace 事件
- `artifacts/`：输入输出样本、stdout、stderr、代码快照
- `candidates/`：候选能力 manifest
- `skills/`：已转正能力与父能力
- `indexes/`：hash、MinHash、结构模板索引、Qdrant 映射
- `fixtures/`：验证样本
- `lineage/`：合并、拆分、晋升、降级历史
- `reports/`：评估指标和批处理报告

---

## 11. 端到端流水线

### 11.1 候选发现

1. 从宿主采集 trace
2. 找出被生成并被调用的脚本/命令
3. 抽取输入输出和入口信息
4. 写入 `candidate`

### 11.2 验证

1. 构造或回收 fixture
2. 在隔离环境重放
3. 记录输出
4. 判断 `Replay Gate` / `Output Gate`

### 11.3 多阶段相似性分析

1. 先做 hash 去重
2. 再做 MinHash / 文本相似
3. 再做 AST 结构归一和结构匹配
4. 最后做 embedding 近邻召回

### 11.4 晋升与合并

1. 判断是否 exact duplicate
2. 判断是否可归入现有父能力
3. 判断是否需要新建父能力
4. 满足条件后转正

### 11.5 检索与复用

1. 新任务到来
2. 按输入类型 + 描述检索
3. 返回前 3 个候选能力
4. 宿主决定是否展开和调用

### 11.6 迭代反馈

1. 记录调用成功率
2. 记录失败样本
3. 更新排序分
4. 触发下一轮批量吸收

---

## 12. MVP 指标

### 12.1 必看指标

- `Replay Pass Rate`
- `Output Pass Rate`
- `Top-1 Recall`
- `Top-3 Recall`
- `Exact Duplicate Rate`
- `Near Duplicate Merge Precision`
- `New Tool Rate`
- `Warm-start Gain`

### 12.2 指标解释

- `Replay Pass Rate`：候选工具能否稳定重放
- `Output Pass Rate`：重放后输出是否达标
- `Top-1 / Top-3 Recall`：检索是否能召回正确能力
- `Exact Duplicate Rate`：发现多少完全重复工具
- `Near Duplicate Merge Precision`：近重复挂靠是否合理
- `New Tool Rate`：新任务里还需要新增多少工具
- `Warm-start Gain`：带库执行相对空库的收益

---

## 13. 实施顺序

### 第 1 步：证据链打通

先做：

- trace 采集
- candidate manifest
- artifact 落盘

先不要做复杂检索。

### 第 2 步：重放验证打通

补齐：

- fixture
- replay runner
- output checker

这一步决定“是不是程序类能力”的边界是否稳。

### 第 3 步：重复检测打通

按顺序接：

1. `BLAKE3`
2. `datasketch`
3. `tree-sitter + ast-grep`
4. `embedding + Qdrant`

### 第 4 步：晋升与父能力结构

只做保守转正和父子挂靠，不做激进自动合并。

### 第 5 步：检索与 MCP 暴露

让正式能力能被宿主召回和调用。

---

## 14. 风险与控制

### 风险 1：误把“能跑”当“正确”

控制：

- 分离 `Replay Gate` 和 `Output Gate`

### 风险 2：近重复误合并

控制：

- 先父能力挂靠
- 不直接融合实现

### 风险 3：规范化规则不稳，hash 失真

控制：

- 保留原始代码快照
- 规范化过程可回放

### 风险 4：语义检索过度召回

控制：

- 先结构过滤
- 再语义排序
- 阈值保守

### 风险 5：MVP 做太大

控制：

- 只做 Python
- 只做文档转 Markdown
- 只做单人场景

---

## 15. 推荐拍板项

如果现在要正式开始做 MVP，我建议你先拍这 5 件事：

1. 宿主只选 `Claude Code`
2. 能力域只选 `document -> markdown`
3. 实现语言先只支持 `Python`
4. 合并策略只做 `父能力 + 子实现`
5. 技术栈采用 `BLAKE3 + datasketch + tree-sitter + ast-grep + embedding + Qdrant`

---

## 16. 一句话收束

这个 MVP 最重要的不是“看起来多智能”，而是先把**证据、回放、去重、保守晋升**这四件事做扎实。只要这四件事立住，后面的自动合并、跨 agent 迁移、团队共享池才值得往上叠。
