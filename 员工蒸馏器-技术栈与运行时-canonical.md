# 员工蒸馏器 · 技术栈与运行时（Canonical）

> owner 版技术栈，取代 `员工蒸馏器-MVP技术栈与流水线*.md` 的"去重流水线"视角。
> 重心：**采集 → 重放 → 属性验证(含 behavior_signature) → 契约抽取 → 沉淀 → 回灌** 这条 MVP 真正要跑通的主脊，以及"无感"如何在运行时被守住。
> 概念模型见 `v0.4` 与 `契约引擎设计`；本文只讲**怎么运行、怎么对接、用什么**。
> 日期：2026-06-20

---

## 1. 运行时总览：三进程 + 一存储

```
┌─ Claude Code（宿主进程）──────────────────────┐
│  你正常干活                                     │
│   │ PostToolUse hook（极轻·静默·<5ms）          │ ← 对接·采集端
│   ▼ append 一行 ToolCallEvent                   │
└────────────────────────────────────────────────┘
        │
        ▼  distiller/traces/   ←——— 存储：文件树 + Qdrant
┌─ 蒸馏 daemon（独立进程·空闲触发·nice·限流）────┐
│  候选发现 → Gate0确定性 → Replay(uv venv沙箱)   │ ← 检测·沉淀
│  → 属性Output Gate(mistune→behavior_signature)  │
│  → 契约抽取 → 目的判同(Qdrant+便宜LLM judge)    │
│  → 三选一 → Batch Composer → 写 skills/         │
└────────────────────────────────────────────────┘
        │ promoted 能力
        ▼
┌─ MCP server（独立进程·常驻）────────────────────┐
│  暴露 promoted 能力为 MCP tool + warm-start(被动) │ ← 对接·回灌端
│  调用前查 R_miss                                 │
└──[CC 经 .mcp.json 连上]──────────────────────────┘
```

三进程把"重活"和"你的会话"物理隔开——这就是无感的结构基础（v0.4 §3.1）。

---

## 2. 进程一：采集 hook（对接·采集端）

### 2.1 怎么对接 CC

CC 原生 hooks，配在 `.claude/settings.json`：

```jsonc
{
  "hooks": {
    "PostToolUse": [
      { "matcher": "Bash|Write|Edit",
        "command": "distiller-capture" }   // 读 stdin JSON，append 一行，退出
    ],
    "Stop": [
      { "command": "distiller-signal-idle" } // 可选：标记会话空闲，供 daemon 选触发窗口
    ]
  }
}
```

### 2.2 职责（只做一件事）

- 从 stdin 拿到工具调用的 JSON（工具名/输入/输出/cwd/exit_code）
- 归一成 `ToolCallEvent`（schema 见 v0.4 §9 + 契约引擎 §3，含 `input/output_artifacts`、`determinism_signals` 占位）
- **append 一行到 `traces/`，退出**

### 2.3 无感硬约束（守则①）

- **只写不算**：不算 hash、不解析代码、不联网——全留给 daemon
- **静默**：不向 stdout/stderr 输出任何内容（否则 CC 会显示）
- **<5ms**：append-only，失败也静默退出，绝不阻塞或报错给 CC

> 技术选型：hook 用编译型小程序或极简脚本（启动快）；事件落 JSONL 追加，或推到 daemon 监听的本地 unix socket（更快、零文件锁）。

---

## 3. 进程二：蒸馏 daemon（检测·沉淀，主脊）

独立后台进程，所有重活在这里。**对前台零可见、零打断**（v0.4 §3.1 守则②③）。

### 3.1 调度（守则②：别抢资源）

- **空闲触发**：靠 `Stop` hook 信号 / 系统负载探测，优先在 CC 空闲窗口批量跑
- **低优先级**：`nice` / IO 优先级降权
- **限流**：并发 venv 数有上限；候选攒批处理，不"一来就重放"

> 配置参考：Yunjue `reproduce/docs/reproduce.md` 的批处理旋钮可照搬形状——`WORKER_TOOL_ENHANCE_INTERVAL`（演化间隔）、`batch_size`（批大小），以及把演化/评估拆成固定入口（`evolve.sh` / `evaluate.py`）。

### 3.2 流水线各阶段与选型

| 阶段 | 干什么 | 技术 | 主/副 |
|---|---|---|---|
| 候选发现 | 从 traces 找"读某类文件→产出 .md 的单入口进程" | 自写规则（受 MVP 范围约束，形状卡死才可做） | 主脊 |
| Gate0 确定性探测 | 静态信号粗筛 + 多次重放实测；**+ 系统二进制检测**（`subprocess` 起 soffice、`import win32com` 等 → 标 `deferred_dependency` + `requires_host_capability`，不静默失败） | tree-sitter（扫网络/模型/随机源/系统二进制调用点）+ 实测 | 主脊 |
| Replay Gate | 隔离环境装依赖、重放复现 | **uv**（per-tool venv）+ temp dir 拷贝输入 | 主脊 |
| 属性 Output Gate | 判合法 md/图片落盘/表格渲染/无大段丢字 → **产出 behavior_signature** | **mistune**（md 解析）+ 自定义断言 + 可选 hypothesis | 主脊 |
| 契约抽取 | 观测 I/O 主锚 + 代码佐证 + 目的 embed + branch_identity + behavior_signature | trace artifacts 的 media_type + tree-sitter 抽入口签名 + embedding | 主脊 |
| 目的判同 | Qdrant 预筛 → LLM 契约级裁决 | **Qdrant** + **便宜 LLM judge**（GPT-5.3 留疑难升级） | 主脊 |
| 三选一分类 | 新工具/新分支/迭代\|重复 | ast-grep（结构等价/薄壳）+ BLAKE3/datasketch（精确/近重） | 副轴 |
| Batch Composer | 挂分支(retained 全保留)、best-of-N 切 active、shared_promotion | 自写 + 回归(pytest) | 主脊 |

### 3.3 隔离沙箱（守则③）

- 每个候选一个 **uv venv**（轻、装依赖快），跑在 **temp 工作目录**
- 输入 = 从 `artifacts/` 拷贝的样本副本，**绝不指向你的项目工作区**
- 阶段二若遇系统依赖（如 LibreOffice）再上 Docker；MVP 纯 Python 库转换 uv 够用

### 3.4 副轴库的定位（沿用 Codex 选型，不变）

`BLAKE3 / datasketch / tree-sitter / ast-grep` 都是 daemon **内部调用的库**，不是独立服务；只服务于"分支内重复 vs 迭代"判定和薄壳识别，**不当合并主轴**（合并主轴是契约/目的）。

---

## 4. 进程三：MCP server（对接·回灌端）

### 4.1 怎么对接 CC

`.mcp.json`（或 `claude mcp add`）指向 distiller MCP server（stdio/http）：

```jsonc
{ "mcpServers": { "distiller": { "command": "distiller-mcp" } } }
```

### 4.2 职责

- 把 `skills/` 里 promoted 能力暴露成 MCP tool（如 `doc_to_markdown`，dispatch 到 branches）
- **`promoted ≠ exposed`**：转正(进库)不等于暴露(上前台工具面)。能力有 `visibility` 阶梯（hidden→searchable→invokable_by_id→mcp_exposed→team_published）。默认只暴露**少量基础工具**（`distiller.search/describe/run_capability`）；只有高置信/高频能力才**二次门槛**后导出为一等 MCP tool（如 `doc_to_markdown`）——避免污染宿主工具列表、避免乱召回（呼应 v0.4"宁漏不乱召回"）
- **warm-start 被动**（守则④）：只让工具可被模型发现，不主动注入提示
- 调用前查 `R_miss`（收紧版：branch+contract+version+env）；命中坏组合则不推荐该分支
- 渐进披露：MCP tool description 只放 L1（目的/契约/适用条件/质量分）
- **不拼链护栏**（借 Yunjue `step_tool_analyzer.md` 的 "NEVER create a composite tool"）：回灌时引导宿主优先复用原子能力，别现拼长链——与 v0.4 §7"最小单元=目的、不沉淀长链"同口径

---

## 5. 存储（多库分工，本地轻量、可扩团队）

这系统的数据是**异构**的，不是"选一个数据库"，而是按性质分家：

| 数据 | 性质 | MVP（单人） | 团队阶段 |
|---|---|---|---|
| `traces/` 事件流 | 高频 append-only | 文件 JSONL | 同 + 归档 |
| `artifacts/` 快照/样本/std* | blob | 文件系统 | 对象存储/共享盘 |
| `skills/` 能力（manifest+分支代码+fixtures） | 代码文件 + md/yaml | 文件系统（可 git） | 共享盘 |
| 元数据/索引/`R_miss`/lineage | 结构化、要事务与查询 | **SQLite**（嵌入、零运维、单文件） | **Postgres** |
| 目的 embedding | 向量检索 | **Qdrant 或 pgvector** | **pgvector**（省掉 Qdrant） |

```text
distiller/
  traces/       # hook append 的 ToolCallEvent（JSONL）
  artifacts/    # 输入输出样本、stdout/stderr、代码快照（重放只用拷贝）
  candidates/   # 未转正候选（含 deferred:nondeterministic）
  skills/       # 转正能力：<purpose>/{manifest, branches/, shared/, fixtures/, lineage/, iteration_log}
  meta.sqlite   # 元数据 / 契约签名索引 / R_miss / lineage 查询（MVP）
  vectors/      # Qdrant 单机数据（或改用 pgvector）
  reports/      # 指标与批处理报告
```

### 5.1 不选 Oracle，不拿 Obsidian 当存储

- **Oracle：否决。** 过重、违背无感（daemon 要低优先级常驻）；免费版（23ai Free/XE）装起来重、有资源上限、授权是雷区（连免费层都有审计风险）。没有任何需求非它不可——SQLite/Postgres+pgvector 全覆盖。
- **Obsidian：只当人看的视图层，不当存储引擎。** AI 友好来自"manifest 是 markdown + 渐进披露"（我们已经这么存），不来自这个 app。daemon 要高频 append、事务、并发、向量检索，笔记 app 扛不了。Obsidian 至多 over `skills/` 给人浏览/审计（对应 v0.4 §3 视图层）。

### 5.2 其它

- 保留策略：`traces/`、`artifacts/` 按时间窗 / 是否已转正 / 是否被 lineage 引用 GC。
- 升级路径：SQLite→Postgres、Qdrant→pgvector 都平滑；全程不碰 Oracle。

---

## 6. 选型决定（拍板版）

| 决定点 | 选 | 理由 |
|---|---|---|
| 隔离运行时 | **uv per-tool venv** | 轻、装依赖快，doc2md 纯 Python 库转换够用；Docker 留阶段二系统依赖 |
| 目的判同 LLM | **默认便宜模型，GPT-5.3 留疑难升级** | judge 是结构化分类、有客观 I/O 锚，不吃前沿推理；按量控成本 |
| md 属性验证 | **mistune** | 轻量 md 解析，配自定义断言出 behavior_signature |
| 结构化存储 | **SQLite（MVP）→ Postgres（团队）** | 嵌入零运维起步，平滑扩到团队 |
| 向量库 | **Qdrant 或 pgvector** | 单机好落地；团队期用 pgvector 与 Postgres 合一 |
| 人看视图 | **Obsidian（可选）over skills/** | 仅浏览/审计，非存储引擎 |
| 副轴去重 | **BLAKE3 + datasketch + tree-sitter + ast-grep** | 沿用，降为副轴 |
| 不上 | **Oracle**、Milvus/Weaviate/OpenSearch、Docker(MVP) | 过重 / 授权雷区 / 对 MVP 不必要 |

---

## 7. MVP 实施顺序（从主脊建起）

1. **证据链 + 采集**：CC `PostToolUse` hook（极轻静默）→ `traces/` → `ToolCallEvent`。先把无感采集跑通。
2. **重放 + 属性验证**：uv venv 沙箱（temp 隔离）→ Replay Gate → mistune 属性 Output Gate → **behavior_signature**。这步决定"是不是可沉淀程序类能力"的边界。
3. **契约 + 判同 + 三选一**：契约抽取 → Qdrant 预筛 → 便宜 judge 裁决 → 三选一分类（迭代vs重复人工 pin 兜底）。
4. **Composer + 沉淀**：挂分支(retained 全留)/active 切换/shared_promotion → 写 `skills/` + lineage。
5. **MCP + 回灌**：MCP server 暴露 + 被动 warm-start + R_miss 检查。
6. **daemon 调度**：空闲触发 + nice + 限流，把 2-5 收进带外异步。

---

## 8. 无感的可验收指标（计入 §14 指标体系）

| 指标 | 约束 | 守则 |
|---|---|---|
| `Hook Latency p99` | < 5ms，且 0 输出 | ① |
| `Daemon CPU/IO @ active` | CC 活跃时占用有上限（throttled） | ② |
| `Sandbox Workspace Touch` | 恒为 0（永不碰工作区） | ③ |
| `Foreground Interruptions` | 0（除被动 MCP 工具出现） | ④ |

> 无感不是"看起来没打扰"，是这 4 个指标可测且达标。任何一个破线，就是回到了"有感"。

---

## 9. 一句话

技术栈的重心不是那堆去重库，而是 **采集(无感) → uv沙箱重放 → mistune属性验证(出behavior_signature) → 契约抽取 → 便宜judge判同 → Composer沉淀 → MCP被动回灌** 这条主脊；三进程的物理隔离 + 4 条守则，让"无感"从口号变成可验收约束。去重库是副轴，judge 用便宜模型，沙箱用 uv，GPT-5.3 只在疑难边界上场。
