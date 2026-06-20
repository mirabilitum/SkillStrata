# SkillStrata

> **无感蒸馏可复用工具库。** 从 Claude Code 代理的真实执行轨迹中，自动发现、验证、合并、沉淀程序类可复用能力，以 MCP 工具形式回灌给后续任务——让"上次写过的那个转换脚本"下次自动出现，不再重搓。

MVP 阶段：团队版去风险原型。337 tests / 12 modules，纯 Python，文档转 Markdown 域。

---

## 快照

```bash
distiller init                    # 初始化数据仓库（一次性）
# 此后你在 Claude Code 里干活 —— 无感采集
# daemon 空闲时蒸馏出可复用工具
distiller ls                      # 看库里有什么
distiller show doc-to-markdown    # 看工具详情 + 分支 + 质量分
distiller usage doc-to-markdown   # 被复用了几次 / 成功还是失败
distiller pending                 # 待审的候选（ambiguous / 高价值）
```

---

## 怎么运行的（三进程，无感）

```
Claude Code（你干活）
  │ PostToolUse hook（<5ms，静默，只追加一行事件）
  ▼
traces/  ← 事件流（JSONL）
  │
  ▼ daemon（独立进程，空闲触发，低优先级，不抢资源）
  ├─ 候选发现   把碎片拼成候选，认出"这好像是 pdf→md"
  ├─ Gate 0      确定性探测 + 系统依赖检测（有 LibreOffice？→ 标搁置不静默丢）
  ├─ Replay      沙箱重放（uv venv + temp 目录，不碰工作区）
  ├─ Output Gate 属性验证（守恒 oracle：输入里可量化的内容有没有活进输出）
  ├─ 契约抽取    I/O 契约 + 行为指纹 = 合并 key
  ├─ 目的判同    这是"同一个工具的新分支"还是"另一个工具"？
  ├─ 三选一      新工具 / 新分支 / 已有分支的就地迭代
  ├─ Composer    挂分支、切 active、保留 fallback
  └─ skills/     沉淀为带 manifest + branches + fixtures + lineage 的能力

skills/ ──MCP server──> Claude Code（下次直接复用，工具出现在工具箱里）
```

**三个关键原则：**

- **无感** — daemon 在带外跑，沙箱在临时目录，采集 hook <5ms。人不被打断。
- **渐进披露** — 回灌时只给工具的元数据（名称/用途/签名/质量分），模型想用再展开。
- **价值靠复用确认** — "工具好不好"不是上来打分，而是看它被几个项目复用了、成功了几次。

---

## 安装

```bash
git clone git@github.com:mirabilitum/SkillStrata.git
cd SkillStrata
python -m pip install -e ".[dev]"
distiller init
```

## 配置（零配置默认跑）

daemon 的凭证与行为通过三项覆盖：

| 层 | 说明 |
|---|---|
| `distiller init --data-dir <path>` | 指定数据目录（默认 `.distiller-data`，已 gitignore） |
| 环境变量 | `ANTHROPIC_API_KEY` / `DISTILLER_DATA_DIR` / `DISTILLER_BATCH_SIZE` / `DISTILLER_REUSE_FREQUENCY_N` |
| config 文件 | `.env` 风格 key=value，路径可通过 `--config` 或默认扫描 |

**Judge（目的判同）默认用 Claude Haiku，复用 CC 凭证；无 key 时优雅退化为 offline 规则引擎（不阻塞主链）。** 见 `src/distiller/config.py` 的解析链。

---

## 项目结构

```
src/distiller/
  contracts.py        # 冻结接口——所有模块共享
  capture.py          # M1 采集：hook 极轻事件
  enrich.py           # M1 daemon 补全（hash/media_type/确定性信号）
  discovery.py        # M2 候选发现：关联→形状过滤→提名
  gate0.py            # M2 确定性探测 + 系统二进制检测（显式搁置，不静默丢）
  replay.py           # M3 沙箱重放（uv venv + temp 隔离）
  output_gate.py      # M3 属性验证（守恒 oracle）+ behavior_signature
  contract_extract.py # M4 契约抽取（I/O 锚 + 代码佐证 + 目的嵌入）
  classify.py         # M4+M5：目的判同 + 三选一（新工具/新分支/迭代）
  composer.py         # M5 沉淀：分支/active/retained/共享后处理
  mcp_server.py       # M6 MCP 暴露（promoted≠exposed）
  warmstart.py        # M6 回灌 + R_miss 检查
  observe.py          # M7a 只读观测（pull）：ls/show/usage/failures
  review.py           # M7b 审查 + 质量门控自动升级
```

---

## 开发

```bash
python -m pytest -q          # 337 tests
python -m pytest --tb=short   # 失败时看详情
git branch                   # mvp/m0-scaffold
```

**工程纪律：** 每个里程碑连测试一起交，运行时数据（.distiller-data/）与密钥绝不入库。去重用到的归一化（ast-grep 归一掉变量名等）只用于检测重复，入库永远是原始实现（带所有边缘处理/年轮）。
