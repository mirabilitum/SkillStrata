# SkillStrata

**无感蒸馏可复用工具库。** 从 agent（Claude Code / Codex / Hermes）的真实执行轨迹中自动发现、验证、合并、沉淀出程序类可复用能力，以 MCP tool 形式回灌给后续任务使用。

> MVP 阶段（v0.4）：团队版去风险原型。设计完整、代码 337 tests/12 modules，纯 Python、文档转 Markdown 域。

## 一句话

你在 CC 里干活——hook 无感抓 trace → daemon 后台蒸馏出可复用工具 → **下次、下个项目、团队另一个人，不用重写，直接复用。**

## 架构（三进程，无感）

```
Claude Code（干活）──hook──> 采集（<5ms）──> distiller daemon（空闲触发，低优先级）
                                        │
                         ┌─ 候选发现 → Gate0 → Replay → Output Gate
                         ├─ 契约抽取 → 目的判同 → 三选一分类
                         └─ Composer → 沉淀 skills/

    skills/ ──MCP──> Claude Code（下次直接复用，warm-start）
```

## 快速开始

```bash
# 初始化
distiller init

# 看库
distiller ls
distiller show doc-to-markdown

# 看效果
distiller usage doc-to-markdown
distiller failures doc-to-markdown

# 待审
distiller pending
```

## 项目结构

```
src/distiller/
  contracts.py      # 冻结接口（所有模块共享）
  capture.py        # M1 采集：hook 无感抓 trace
  enrich.py         # M1 daemon 补全
  discovery.py      # M2 候选发现：关联→形状过滤→提名
  gate0.py          # M2 确定性探测 + 系统依赖检测
  replay.py         # M3 沙箱重放
  output_gate.py    # M3 属性验证（守恒 oracle）+ behavior_signature
  contract_extract.py # M4 契约抽取
  classify.py       # M4+M5 目的判同 + 三选一
  composer.py       # M5 沉淀：分支/迭代/共享后处理
  mcp_server.py     # M6 MCP 暴露（promoted≠exposed）
  warmstart.py      # M6 回灌 + R_miss
  observe.py        # M7a 只读观测（pull）
  review.py         # M7b 审查动作 + 质量门控
tests/ — 337 tests, 100% 绿
```

## 设计文档（现行四件套）

- `员工蒸馏器-设计文档-v0.4.md` — 主干
- `员工蒸馏器-契约引擎设计.md` — 合并发动机
- `员工蒸馏器-技术栈与运行时-canonical.md` — 实现
- `员工蒸馏器-从doc2md反推蒸馏路径.md` — 论据（年轮模型）

详见 `00-索引.md`（完整文档地图）。Codex 的辅助产出在 `forcodex/`（不入库）。

## 开发

```bash
git checkout mvp/m0-scaffold
python -m pytest -q         # 337 tests
distiller init               # 端到端
```

## 许可

MIT
