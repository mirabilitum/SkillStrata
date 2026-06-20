# 员工蒸馏器 · 三选一阈值与 Composer 的 shared_promotion

> 把两处之前留作"人工 pin / 软门槛"的自动判定钉实：
> 1. 三选一里最易判错的"迭代 vs 重复"该用什么阈值
> 2. shared_promotion（共享后处理提级）怎么自动判"增益"
> 两者都以刚定义的 `behavior_signature`（见 `属性OutputGate与behavior_signature.md`）为度量工具。
> 日期：2026-06-20

---

## 0. 定位：behavior_signature 是这两个判定的共同仪器

- 三选一（契约引擎 §5）：前两类（新工具 / 新分支）靠契约就能定，**只有"同分支下：迭代还是重复"难**——之前 MVP 留作人工 pin。
- Composer（契约引擎 §6.1）：shared_promotion 之前只有"≥2 分支受益"这句软话，没说怎么测"受益"。

两者都缺一个**客观度量**。`behavior_signature` 正好是——这也回头印证了"先做 Output Gate"的顺序对。

---

## 1. 迭代 vs 重复：behavior_signature 给出偏序，偏序驱动判定

新候选 C 已匹配到某现有分支 B（同契约、同 branch_identity）。可用的客观信号：

- **结构相似**：ast-grep 归一后 C 与 B 的 AST 是否近等
- **行为偏序**：`behavior_signature(C)` vs `behavior_signature(B)` —— 支配 / 相等 / 不可比
- **R_miss 命中**：B 在 R_miss 里记过的失败输入，C 能不能跑过

### 1.1 判定格（从强到弱）

```
1. C 跑过了 B 的 R_miss 里的失败输入（B 失败、C 成功）
      → iteration（最硬信号：C 补了真实缺口）

2. 结构近等 且 behavior_signature 相等
      → duplicate（丢弃 / 仅 +1 复用计数）

3. behavior_signature(C) 支配 B（所有轴 ≥，至少一轴 >）
      → iteration（C 设为 active_impl，B 进 retained）

4. behavior_signature(B) 支配 C（C 是更弱的副本/回退）
      → duplicate，丢 C 留 B

5. 不可比（各有取舍：C 在某轴更好、另一轴更差；或结构不同但同契约）
      → ambiguous
```

### 1.2 关键设计：不可比就不自动判

第 5 类是真实存在的（比如 C 表格更好但丢了图）。**强行二选一是错的**——它可能是该并列保留的变体。处理：

- **MVP**：ambiguous → 人工 pin（这就是契约引擎 §5 那句"人工兜底"的精确触发条件，不是所有同分支都 pin，只 pin 不可比的）。
- **阶段二**：ambiguous → 两个实现都进 `retained_impls`，`active_impl` 按聚合分（成功率 + 覆盖 grade）选，不丢任何一个。

> `behavior_signature` 把实现关系变成**偏序**（支配/相等/不可比），判定只在"可比"时自动，"不可比"时保守——这就是阈值的本质，不是某个相似度数字卡线，而是偏序结构。

---

## 2. shared_promotion：先过结构资格，再做实测实验

把某分支里的后处理 P（如 `table_to_list`）提到父级、作用所有分支，分两关：

### 2.1 关一：结构资格（先廉价砍掉不该提的）

P 必须**作用于共享输出表示（md 字符串 / md AST），是 md→md，无分支内部依赖**。

- `table_to_list`：处理最终 md → **合格**
- `sanitize_text`：处理最终 md → **合格**
- `_repair_docx_relationships`：处理 docx XML 内部 → **不合格**（分支私有，永不提级）

> 判据：看 P 的输入类型——是共享 md，还是某分支的私有结构。后者直接出局，连实验都不做。这砍掉了"局部修补被误推全局"的大部分风险。

### 2.2 关二：实测实验（用 behavior_signature 量增益）

对每个**其它**分支：跑该分支 → 产 md → 套用 P → 重过 Output Gate → 比对前后 `behavior_signature`。

提级判据（全满足）：
1. **≥2 个分支** behavior_signature 出现**改善**（如 `table_render_mode` pipe→kv_list、覆盖 grade 不降）
2. **0 个分支回退**（任何轴退化 / 任何 fixture 失败 → 否决）
3. 提级后仍 `retained` 在 branch 层、**可降回**；将来某分支回归自动降级

> shared_promotion 本质是个**实验**：拿 P 在别的分支 fixture 上真跑一遍，用 behavior_signature 量出"是不是纯增益"。不是"看着通用就提"。

---

## 3. 两者共用一套仪器（顺序印证）

| 判定 | 用 behavior_signature 干什么 |
|---|---|
| 迭代 vs 重复 | 比 C 与 B 的指纹偏序（支配/相等/不可比） |
| shared_promotion | 比 P 套用前后各分支的指纹增益 |

都靠"指纹可比对"。所以 Output Gate（产指纹）必须先立——这条主脊顺序是对的。

---

## 4. doc2md 走一遍

**迭代 vs 重复**：
- 项目D 的 docx 候选 C，匹配到已有 docx 分支 B。B 在 R_miss 里记过"关系损坏的 docx 崩溃"，C（带 `_repair_docx_relationships`）跑过了这个输入 → **判定格第 1 条 → iteration**，C 设 active、B 留 retained，挂回归。

**shared_promotion**：
- `table_to_list` 当前在 docx 分支里。结构资格：它处理最终 md → 合格。
- 实验：套到 pdf、pptx、xlsx 分支的 fixture → 三者 `table_render_mode` 都 pipe→kv_list、覆盖 grade 不降、无 fixture 失败 → **≥2 改善、0 回退 → 提级到 shared**。
- `_repair_docx_relationships`：结构资格就不过（碰 docx XML 内部）→ 永远留在 docx 分支。

---

## 5. 一句话

这两处自动判定的钥匙都是 **behavior_signature 可比对**：迭代 vs 重复 = 比 C/B 指纹的**偏序**，可比才自动、不可比就保守（MVP 人 pin、阶段二并列保留）；shared_promotion = **结构资格 + 实测实验**，P 必须作用于共享 md、且在 ≥2 分支 fixture 上实测纯增益才提。阈值不是某个魔数，而是"偏序结构 + 实验门禁"——客观、可回退、不误伤年轮。
