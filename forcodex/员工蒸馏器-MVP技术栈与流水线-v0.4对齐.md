# 员工蒸馏器 · MVP 技术栈与流水线 v0.4 对齐版

> 承接：
> - `员工蒸馏器-设计文档-v0.4.md`
> - `员工蒸馏器-MVP技术栈与流水线.md`
>
> 这份文档的目标，是把上一版偏“拆小工具”的 MVP 流水线，改成与 v0.4 一致的实现视角：
> **最小单元 = 自洽目的，合并主轴 = 契约/目的，工具沿分支与迭代轴生长。**
> 日期：2026-06-20

---

## 1. 一句话结论

MVP 不再把 `doc2md` 这种真实工具理解成“多个小工具的集合”，而是把它视为：

- 一个自洽目的
- 一个统一契约
- 多个输入分支
- 若干共享后处理
- 一条持续迭代的年轮轴

技术栈上，`BLAKE3 / datasketch / tree-sitter / ast-grep / embedding / Qdrant` 仍然有用，但它们的角色变了：

- **主轴**：契约签名 + 目的聚类 + 三选一分类
- **副轴**：代码相似、文本近重、薄壳识别

---

## 2. MVP 真正要做什么

MVP 只回答一个问题：

**能不能从真实 trace 里，把反复手搓的“文档转 Markdown”碎片，长成一个 `doc2md` 形态的成熟能力。**

它不是在做：

- 自动拆出一堆 `pdf-to-md / docx-to-md / xlsx-to-md` 小工具
- 自动把每个函数都注册成 skill
- 追求代码层面的统一实现

它在做的是：

1. 识别某个候选是否属于既有“目的”
2. 判断它是新工具、新分支，还是对已有分支的就地迭代
3. 保留工具年轮，而不是把边缘处理抹平

---

## 3. 核心建模

### 3.1 最小单元

最小单元不是最小函数，也不是最小格式处理器，而是**最小可复用目的**。

示例：

- `doc-to-markdown`：是一个单元
- `video-to-script-to-video`：不是一个单元
- `doc-to-markdown + OCR 识图`：如果混在一起，通常也不是一个确定性同质单元

### 3.2 工具内部形态

MVP 默认把一个成熟能力建模成：

```text
purpose
  + contract
  + branches
  + shared_post_processing
  + iteration_log
```

### 3.3 每个新碎片只有三种去向

一个通过基础验证的新碎片，只能进入以下三类之一：

1. `new_skill`
2. `new_branch`
3. `branch_iteration`

这三类比“新工具 / 重复”更贴近真实世界。

---

## 4. 以 `doc2md.py` 为目标终态

按 v0.4 的理解，`doc2md.py` 不应被拆成多个平级技能，而应建模成一个能力：

```text
skill: doc-to-markdown
  contract:
    input: file + type
    output: markdown + assets
  branches:
    - pdf
    - docx
    - xlsx
    - pptx
    - generic
  shared_post_processing:
    - sanitize_text
    - table_to_list
  iteration_log:
    - 老格式兼容
    - docx 关系修复
    - 键值表识别
    - 扫描版 PDF 特判
```

关键点：

- `process_pdf` 和 `process_docx` 是同一目的下的不同输入路径
- `_repair_docx_relationships` 更像对 `docx` 分支的就地迭代
- `table_to_list` 和 `sanitize_text` 更像被提升到父能力的共享后处理

---

## 5. MVP 边界

### 5.1 纳入范围

- Claude Code
- Python
- 文档转 Markdown 这一单一目的
- 纯确定性或确定性同质单元
- 可重放、可保存样本、可做属性验证的能力

### 5.2 不纳入范围

- 提示词沉淀
- 任意长链自动拆 DAG
- 团队共享池
- OCR/LLM/联网等非确定性分支的自动转正
- 跨宿主一致体验

---

## 6. 技术栈的重新定位

### 6.1 主轴技术

#### `Pydantic` 或等价 schema 工具

用途：

- 定义输入输出契约
- 产出标准化契约签名

为什么现在更重要：

- v0.4 以后，合并主轴不再是代码相似，而是契约/目的
- 没有稳定契约，就没有稳定的“同目的判断”

#### `Qdrant`

用途：

- 存储目的摘要 embedding
- 支持“同目的近邻召回 + payload 过滤”

为什么现在更重要：

- 它不只是检索工具名，而是帮我们在契约模糊时找“可能属于同一目的”的候选

#### `pytest` 或轻量回放框架

用途：

- 跑 Replay Gate
- 跑 Output Gate
- 跑共享后处理回归

为什么现在更重要：

- v0.4 以后，“分支迭代不能把其它分支搞坏”是核心约束

### 6.2 副轴技术

#### `BLAKE3`

用途：

- 规范化 manifest / 模板代码的 exact duplicate 检测

定位：

- 抓完全重复，不负责主合并逻辑

#### `datasketch`

用途：

- README、说明、提示文字的近重复召回

定位：

- 只提供“近邻线索”

#### `tree-sitter`

用途：

- 做结构解析

定位：

- 帮助判断“重复 vs 迭代”
- 帮助识别薄壳实现

#### `ast-grep`

用途：

- 结构归一化
- AST 层比对

定位：

- 只做分支内辅助判断
- 不再承担“主合并依据”

#### `FlagEmbedding` 或 `sentence-transformers`

用途：

- 对目的摘要、任务描述、能力说明做 embedding

定位：

- 服务“目的聚类”
- 不是“相似就合并”

### 6.3 不建议在 MVP 上太重的组件

- `Milvus`
- `Weaviate`
- `OpenSearch`
- `Open-NiCad`
- `SourcererCC`

原因：

- 对当前问题过重
- 更偏平台或学术 clone detection
- 不利于先把契约/目的主轴跑通

---

## 7. 数据结构

### 7.1 Skill Manifest

```yaml
name: doc-to-markdown
purpose: 任意文档转换为 LLM 友好的 markdown
contract:
  input:
    document_path: file
    type: auto|pdf|docx|xlsx|pptx|generic
  output:
    markdown: string
    assets_dir: dir
determinism: deterministic
quality:
  reuse_count: 12
  success_rate: 0.93
branches:
  - key: pdf
    impl_ref: ./branches/pdf.py
    fixtures_ref: ./fixtures/pdf/
  - key: docx
    impl_ref: ./branches/docx.py
    fixtures_ref: ./fixtures/docx/
  - key: generic
    impl_ref: ./branches/generic.py
    is_thin_wrapper: true
shared_post_processing:
  - sanitize_text
  - table_to_list
iteration_log:
  - ver: 3
    branch: docx
    change: add repair for broken relationships
    regression: pass
```

### 7.2 Candidate Manifest

```yaml
id: candidate-uuid
purpose_guess: document-to-markdown
contract_signature: hash-or-json
determinism: deterministic
branch_hint: docx
source_trace_ids:
  - trace-1
  - trace-2
validation:
  replay_pass: true
  output_pass: true
classification:
  kind: pending
  nearest_skill: doc-to-markdown
  nearest_branch: docx
```

### 7.3 三选一分类结果

```yaml
decision:
  kind: branch_iteration
  target_skill: doc-to-markdown
  target_branch: docx
  reason:
    - same purpose
    - same contract
    - fixes branch-specific edge case
```

---

## 8. 目录结构

```text
distiller/
  traces/
  artifacts/
  candidates/
  skills/
    doc-to-markdown/
      manifest.yaml
      branches/
        pdf.py
        docx.py
        xlsx.py
        pptx.py
        generic.py
      shared/
        sanitize_text.py
        table_to_list.py
      fixtures/
        pdf/
        docx/
        shared/
      lineage/
      iteration_log.yaml
  indexes/
  reports/
```

### 8.1 为什么这样分

- `branches/`：同一目的下的输入分支
- `shared/`：跨分支共享的后处理年轮
- `fixtures/shared/`：共享后处理回归集
- `iteration_log.yaml`：把“就地迭代”显式化

---

## 9. 端到端流水线

### Step 1：采集 trace

从 Claude Code 收集：

- 执行入口
- 输入文件
- 输出文件
- 依赖
- stdout / stderr
- 文件改动

### Step 2：Gate 0 确定性探测

判断候选能力是：

- `deterministic`
- `nondeterministic`
- `mixed`

处理原则：

- `deterministic`：进入后续流程
- `mixed`：尝试沿确定性边界切开
- `nondeterministic`：记录，不自动转正

### Step 3：Replay Gate

在隔离环境中重放，确认：

- 能跑
- 依赖可装
- 无未声明环境依赖

### Step 4：Output Gate

这里按 v0.4 修正，不做“一刀切基线 diff”。

对 `doc2md` 类能力，优先做：

- 产出是合法 Markdown
- 图片引用都有落盘文件
- 表格/键值结构被渲染
- 无大段内容丢失
- 共享后处理不破坏已有分支

### Step 5：生成契约签名

对候选能力抽取：

- 目的摘要
- 输入类型
- 输出类型
- 确定性等级

这一步的产物是后续合并主轴。

### Step 6：找到最近邻 skill

先按契约匹配，再按目的 embedding 找近邻。

输出：

- 最近 skill
- 最近 branch
- 是否同目的

### Step 7：三选一分类

分类规则：

1. 不匹配任何已知目的：`new_skill`
2. 匹配 skill，但缺这个输入路径：`new_branch`
3. 匹配 skill，且输入路径已存在：进入 `duplicate vs iteration`

### Step 8：重复 vs 迭代判定

这一步才使用副轴证据：

- `tree-sitter`
- `ast-grep`
- `BLAKE3`
- `datasketch`

判定逻辑：

- 结构等价且无新行为：`duplicate`
- 修复边缘、补健壮性、补共享后处理：`branch_iteration`

MVP 阶段这一小步允许人工 pin 兜底。

### Step 9：更新 skill

根据分类结果更新能力：

- `new_skill`：建新目录
- `new_branch`：在 skill 下新增 branch
- `branch_iteration`：版本 +1，写 `iteration_log`

### Step 10：回归

分支更新后必须跑：

- 当前分支 fixture
- 共享后处理 fixture
- 已有 branch 的基本回归

### Step 11：MCP 暴露与 warm-start 回灌

后续任务到来时：

- 先按目的/契约检索已存在能力
- 注入 L1 元数据
- 宿主优先调用而不是重搓

---

## 10. 开源库在 `doc2md` 场景里的具体角色

### `markitdown`

在这个场景里不是统一 oracle，而是双重角色：

- 对 `generic` 分支：兜底实现
- 对自定义分支：可作为有限对照基线

所以不能用“和 markitdown 一样”定义正确性。

### `tree-sitter + ast-grep`

主要用来识别：

- 这是不是一个薄壳包装
- 这个候选和已有分支是不是结构上几乎一样
- 它更像重复，还是更像在原分支上加了伤疤

### `Qdrant + embedding`

主要用来判断：

- 这是不是“文档转 Markdown”这一目的的延长
- 该挂到哪个已有 skill

不是用来直接决定“合并成功”。

---

## 11. 成功标准

MVP 成功要看这些，而不是“自动化程度很高”：

1. 从 trace 中长出至少 1 个 `doc-to-markdown` 类能力
2. 这个能力至少有 3 个输入分支
3. 至少出现 1 次“就地迭代被正确识别”，没有被误判成新工具
4. 至少出现 1 次 warm-start 命中，后续任务直接复用而非重搓
5. 共享后处理回归能拦住一次分支更新带来的退化

---

## 12. 核心指标

- `Replay Pass Rate`
- `Output Property Pass Rate`
- `Contract Merge Precision`
- `Branch Growth`
- `Iteration Classification Accuracy`
- `Iteration Regression Pass Rate`
- `Warm-start Hit Rate`
- `Warm-start Gain`
- `Determinism Split Rate`
- `Review Load`

### 12.1 这几个指标各自看什么

- `Contract Merge Precision`：契约/目的合并是否判对
- `Branch Growth`：一个目的是不是在健康生长，而不是爆炸成平级工具
- `Iteration Classification Accuracy`：新碎片有没有被正确识别成“迭代”
- `Warm-start Hit Rate`：宿主有没有在该复用时真的复用

---

## 13. 实施顺序

### 第一阶段

- trace 采集
- Gate 0 / Replay / Output Property
- contract signature 生成
- skill / branch 基本目录结构

### 第二阶段

- purpose embedding + Qdrant
- 三选一分类
- duplicate vs iteration 的副轴判断

### 第三阶段

- shared post-processing 回归
- MCP 暴露
- warm-start 回灌

---

## 14. 一句话收束

v0.4 对齐后的 MVP，不再追求“把工具拆小”，而是追求**识别一个目的如何生长**。真正重要的不是把 `doc2md` 拆成多少片，而是能不能看懂：哪个碎片该成为新 skill，哪个该挂成新分支，哪个其实只是给老分支添了一道年轮。
