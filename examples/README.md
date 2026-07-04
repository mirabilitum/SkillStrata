# examples/

参考实现，**不属于 `distiller` 包**，不被 CLI / pipeline / 测试 import。

## `doc2md.py`

一个人工沉淀好的真实文档转换工具（约 920 行，覆盖 pdf/docx/xlsx/pptx/老格式/html/txt；
图片原位、表格 LLM 友好化、老格式兜底）。它是**设计的"尺子"**——蒸馏器该沉淀出的终态样本长什么样，
参见 `docs/员工蒸馏器-从doc2md反推蒸馏路径.md`。

放在这里的原因（复审 2026-07-04 P2 落地）：它是**参考实现**，不是内置 skill，也没接进 pipeline。
放在包外避免"哪个是产品主路径"的歧义。

### 注意：它不能直接被 Replay Gate 重放

`replay.replay()` 的约定是「子进程的 **stdout** 即 markdown 输出」。而 `doc2md.py` 的
`main()` 把 markdown **写进文件**，只往 stdout 打印一行 `已生成: <路径>`。所以直接拿它重放，
replay 抓到的 stdout 是路径字符串，不是 markdown——过不了 Output Gate。

这不是 bug，是两种正当的 I/O 契约：CLI 工具落文件，蒸馏沙箱要 stdout。要让 doc2md 成为可蒸馏候选，
需要一个「打印 markdown 到 stdout」的适配入口（团队阶段的 host-capability 重放会一并解决老格式分支）。
`tests/test_pipeline_e2e.py` 里的转换器 fixture 就是按 stdout 契约写的，用来验证整条流水线。

### 安全边界（复审 2026-07-04 P2-e）

它处理的是**不可信文档**，已加最小边界：
- zip（docx/xlsx/pptx 本质是 zip）解压前做 bomb / 路径穿越预检（条目数、解压总大小、`..` 逃逸）。
- 外部转换进程（LibreOffice / Word COM）统一带 timeout。

作为参考实现，边界点到为止；生产化还需输出路径白名单、更细的资源配额与 COM 进程回收。
