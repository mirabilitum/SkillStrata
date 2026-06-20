import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const SLIDE_W = 1280;
const SLIDE_H = 720;
const FRAME = { left: 72, top: 64, width: 1136, height: 592 };

const COLORS = {
  bg: "#F5EFE5",
  paper: "#FFFDF8",
  ink: "#18181B",
  muted: "#57534E",
  line: "#D6CCBC",
  accent: "#C96A1B",
  accentSoft: "#EEDAC6",
  teal: "#0F766E",
  tealSoft: "#DDEFEA",
  plum: "#7C3AED",
  danger: "#B45309",
  darkPanel: "#23211E",
};

async function writeBlob(filePath, blob) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

function addText(slide, {
  left,
  top,
  width,
  height,
  text,
  fontSize = 20,
  color = COLORS.ink,
  bold = false,
  align = "left",
  verticalAlign = "top",
  fill = "none",
  lineFill = "none",
  lineWidth = 0,
  italic = false,
  opacity,
}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
  });
  shape.text = text;
  shape.text.style = {
    fontSize,
    bold,
    italic,
    color,
    alignment: align,
    verticalAlignment: verticalAlign,
  };
  if (opacity !== undefined) {
    shape.opacity = opacity;
  }
  return shape;
}

function addBox(slide, {
  left,
  top,
  width,
  height,
  fill = COLORS.paper,
  lineFill = COLORS.line,
  lineWidth = 1,
  radius = "rounded-xl",
  shadow = "shadow-sm",
}) {
  return slide.shapes.add({
    geometry: "roundRect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
    borderRadius: radius,
    shadow,
  });
}

function addTag(slide, text, left, top, width = 220, fill = COLORS.accentSoft, color = COLORS.accent) {
  addBox(slide, {
    left,
    top,
    width,
    height: 34,
    fill,
    lineFill: fill,
    lineWidth: 0,
    radius: "rounded-full",
    shadow: "none",
  });
  addText(slide, {
    left: left + 14,
    top: top + 7,
    width: width - 28,
    height: 20,
    text,
    fontSize: 12,
    color,
    bold: true,
  });
}

function addSlideChrome(slide, index, total) {
  slide.background.fill = COLORS.bg;
  slide.shapes.add({
    geometry: "rect",
    position: { left: 0, top: 0, width: 26, height: SLIDE_H },
    fill: COLORS.accent,
    line: { style: "solid", fill: COLORS.accent, width: 0 },
  });
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: 980, top: -170, width: 420, height: 420 },
    fill: COLORS.accentSoft,
    line: { style: "solid", fill: COLORS.accentSoft, width: 0 },
  });
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: 1040, top: 520, width: 220, height: 220 },
    fill: COLORS.tealSoft,
    line: { style: "solid", fill: COLORS.tealSoft, width: 0 },
  });
  addText(slide, {
    left: 72,
    top: 24,
    width: 260,
    height: 18,
    text: "手艺人蒸馏器 xs / internal pre",
    fontSize: 11,
    color: COLORS.muted,
    bold: true,
  });
  addText(slide, {
    left: 1140,
    top: 24,
    width: 68,
    height: 18,
    text: `${index}/${total}`,
    fontSize: 11,
    color: COLORS.muted,
    bold: true,
    align: "right",
  });
}

function addTitle(slide, title, subtitle) {
  addText(slide, {
    left: FRAME.left,
    top: FRAME.top,
    width: 880,
    height: 58,
    text: title,
    fontSize: 35,
    color: COLORS.ink,
    bold: true,
  });
  if (subtitle) {
    addText(slide, {
      left: FRAME.left,
      top: FRAME.top + 50,
      width: 860,
      height: 42,
      text: subtitle,
      fontSize: 18,
      color: COLORS.muted,
    });
  }
}

function addBulletList(slide, items, left, top, width, lineHeight = 30, fontSize = 19, color = COLORS.ink) {
  items.forEach((item, idx) => {
    addText(slide, {
      left,
      top: top + idx * lineHeight,
      width: 22,
      height: 24,
      text: "•",
      fontSize,
      color,
      bold: true,
    });
    addText(slide, {
      left: left + 22,
      top: top + idx * lineHeight,
      width: width - 22,
      height: lineHeight,
      text: item,
      fontSize,
      color,
    });
  });
}

function addNumberedStrip(slide, x, y, w, h, num, title, body, fill) {
  addBox(slide, {
    left: x,
    top: y,
    width: w,
    height: h,
    fill,
    lineFill: fill,
    lineWidth: 0,
    radius: "rounded-2xl",
  });
  addText(slide, {
    left: x + 18,
    top: y + 16,
    width: 54,
    height: 36,
    text: String(num).padStart(2, "0"),
    fontSize: 26,
    color: COLORS.accent,
    bold: true,
  });
  addText(slide, {
    left: x + 92,
    top: y + 14,
    width: w - 110,
    height: 28,
    text: title,
    fontSize: 20,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: x + 92,
    top: y + 44,
    width: w - 110,
    height: h - 58,
    text: body,
    fontSize: 15,
    color: COLORS.muted,
  });
}

function buildSlide1(slide) {
  addSlideChrome(slide, 1, 12);
  addTag(slide, "内部预演 / 社畜精细化蒸馏", 72, 92, 270);
  addText(slide, {
    left: 72,
    top: 150,
    width: 720,
    height: 140,
    text: "手艺人蒸馏器",
    fontSize: 58,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 72,
    top: 270,
    width: 720,
    height: 110,
    text: "把社畜拿命试出来的零散做法，精细蒸馏成下次不用重写的工具、熟路和团队资产。",
    fontSize: 26,
    color: COLORS.muted,
  });
  addText(slide, {
    left: 72,
    top: 425,
    width: 560,
    height: 78,
    text: "这版 PPT 不是对外融资 deck，而是内部预演：先把一个目的跑通，再决定是否放大到团队与项目组。",
    fontSize: 18,
    color: COLORS.ink,
  });
  addBox(slide, {
    left: 812,
    top: 150,
    width: 370,
    height: 422,
    fill: COLORS.darkPanel,
    lineFill: COLORS.darkPanel,
    lineWidth: 0,
    radius: "rounded-3xl",
    shadow: "shadow-md",
  });
  addText(slide, {
    left: 846,
    top: 190,
    width: 280,
    height: 28,
    text: "今天这一版讲三件事",
    fontSize: 16,
    color: "#E7E5E4",
    bold: true,
  });
  addText(slide, {
    left: 846,
    top: 236,
    width: 280,
    height: 70,
    text: "1. 为什么不是知识库，而是会自己长的手艺库",
    fontSize: 21,
    color: "#FFFFFF",
    bold: true,
  });
  addText(slide, {
    left: 846,
    top: 326,
    width: 280,
    height: 82,
    text: "2. 为什么 `doc2md`\n逼着我们改掉原来的拆分思路",
    fontSize: 21,
    color: "#FFFFFF",
    bold: true,
  });
  addText(slide, {
    left: 846,
    top: 432,
    width: 280,
    height: 94,
    text: "3. 为什么终局不是个人外挂，\n而是整个项目组的熟路网",
    fontSize: 20,
    color: "#FFFFFF",
    bold: true,
  });
}

function buildSlide2(slide) {
  addSlideChrome(slide, 2, 12);
  addTitle(slide, "问题不是没人会做，而是团队记不住自己会做什么", "重复重写、隐性 know-how 和交接损耗，正在把熟路重新打回生路。");
  addText(slide, {
    left: 72,
    top: 176,
    width: 480,
    height: 120,
    text: "我们最常见的浪费，不是“没人写过”，而是“写过，但只活在某次对话、某个临时脚本、某个老师傅脑子里”。",
    fontSize: 28,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 72,
    top: 320,
    width: 470,
    height: 160,
    text: "结果就是：同一类文档转换、表格修补、路径整理、失败回退，agent 和人都会一遍遍重来。越是杂活，越难沉淀；越难沉淀，越容易永远重复。",
    fontSize: 20,
    color: COLORS.muted,
  });
  addNumberedStrip(slide, 610, 172, 520, 88, 1, "临时脚本满天飞", "能跑一次，不等于下次找得到、看得懂、敢复用。", COLORS.paper);
  addNumberedStrip(slide, 610, 278, 520, 88, 2, "交接只交结果，不交手法", "新人接到的是文件，不是为什么这么做、坏了怎么回退。", COLORS.tealSoft);
  addNumberedStrip(slide, 610, 384, 520, 88, 3, "agent 每次都从零开始假装聪明", "没有 reuse-before-create，就只能继续重搓。", COLORS.accentSoft);
  addNumberedStrip(slide, 610, 490, 520, 88, 4, "团队层真正损失的是熟路", "最贵的不是脚本本身，而是踩坑踩出来的判断和伤疤。", "#F2E8E0");
}

function buildSlide3(slide) {
  addSlideChrome(slide, 3, 12);
  addTitle(slide, "它是什么，不是什么", "先把边界说清楚，后面所有实现选择才不会跑偏。");
  addBox(slide, {
    left: 72,
    top: 176,
    width: 520,
    height: 386,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addTag(slide, "是", 102, 204, 66, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 102,
    top: 256,
    width: 436,
    height: 92,
    text: "从真实工作轨迹中，提取反复出现且可验证的程序类能力，让它们沿“目的 / 契约 / 分支 / 年轮”慢慢长成成熟工具。",
    fontSize: 24,
    color: COLORS.ink,
    bold: true,
  });
  addBulletList(slide, [
    "先观察真实干活，再决定值不值得入库",
    "默认保留伤疤，不把复杂经验洗成 canonical 小样",
    "价值靠持续复用确认，不靠和 baseline 做 diff 比输赢",
  ], 102, 382, 430, 34, 18, COLORS.muted);

  addBox(slide, {
    left: 636,
    top: 176,
    width: 572,
    height: 386,
    fill: COLORS.darkPanel,
    lineFill: COLORS.darkPanel,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "不是", 666, 204, 86, "#3B3026", "#F4D6B8");
  addText(slide, {
    left: 666,
    top: 258,
    width: 468,
    height: 48,
    text: "不是一个更大的知识库，也不是一个更烦人的审核系统。",
    fontSize: 25,
    color: "#FFFFFF",
    bold: true,
  });
  addBulletList(slide, [
    "不是监控员工：看的是工具痕迹与 I/O，不是绩效画像",
    "不是 prompt 仓库：提示词沉淀在 MVP 明确 deferred",
    "不是把所有好东西立刻公开：promoted 不等于 exposed",
    "不是强迫人配合：采集无感，审查 pull，不靠弹窗催办",
  ], 666, 338, 468, 36, 18, "#E7E5E4");
}

function buildSlide4(slide) {
  addSlideChrome(slide, 4, 12);
  addTitle(slide, "`doc2md` 不是例子，它是设计的尺子", "真正把架构掰正的，不是抽象原则，而是一个已经长出年轮的真实工具。");

  addBox(slide, {
    left: 72,
    top: 176,
    width: 560,
    height: 396,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });

  addBox(slide, {
    left: 248,
    top: 310,
    width: 208,
    height: 92,
    fill: COLORS.accent,
    lineFill: COLORS.accent,
    lineWidth: 0,
    radius: "rounded-2xl",
  });
  addText(slide, {
    left: 276,
    top: 330,
    width: 160,
    height: 46,
    text: "doc2md",
    fontSize: 30,
    color: "#FFFFFF",
    bold: true,
    align: "center",
  });
  const branches = [
    { x: 108, y: 220, text: "pdf\ntext / scanned", fill: COLORS.tealSoft },
    { x: 410, y: 220, text: "docx\nrepair scars", fill: COLORS.accentSoft },
    { x: 108, y: 430, text: "xlsx / pptx\nstructure-first", fill: "#ECE7F9" },
    { x: 410, y: 430, text: "generic\nmarkitdown fallback", fill: "#EFEAE2" },
  ];
  for (const branch of branches) {
    addBox(slide, {
      left: branch.x,
      top: branch.y,
      width: 150,
      height: 84,
      fill: branch.fill,
      lineFill: branch.fill,
      lineWidth: 0,
      radius: "rounded-2xl",
      shadow: "none",
    });
    addText(slide, {
      left: branch.x + 18,
      top: branch.y + 14,
      width: 114,
      height: 54,
      text: branch.text,
      fontSize: 16,
      color: COLORS.ink,
      bold: true,
      align: "center",
    });
  }
  addBox(slide, {
    left: 160,
    top: 514,
    width: 384,
    height: 44,
    fill: COLORS.darkPanel,
    lineFill: COLORS.darkPanel,
    lineWidth: 0,
    radius: "rounded-full",
    shadow: "none",
  });
  addText(slide, {
    left: 178,
    top: 526,
    width: 348,
    height: 18,
    text: "shared post-processing / artifacts / fallback / scars",
    fontSize: 13,
    color: "#F5F5F4",
    bold: true,
    align: "center",
  });

  addText(slide, {
    left: 684,
    top: 196,
    width: 450,
    height: 70,
    text: "它逼着我们承认三件事",
    fontSize: 30,
    color: COLORS.ink,
    bold: true,
  });
  addBulletList(slide, [
    "最小单元不是最小函数，而是一个自洽目的。`任意文档 → markdown` 就是一个单元。",
    "合并主轴不是代码相似，而是契约 / 目的。分支不同，仍然可以属于同一能力。",
    "好工具不是干净到没伤疤，而是把格式扩展、失败修补和输出手艺都长进去了。",
    "markitdown 是 baseline，不是 oracle。`doc2md` 的价值正是故意做得和 baseline 不一样。",
  ], 684, 284, 440, 58, 19, COLORS.muted);
}

function buildSlide5(slide) {
  addSlideChrome(slide, 5, 12);
  addTitle(slide, "核心闭环：不是收集代码，而是把碎片长成能力", "capture -> replay -> validate -> classify -> compose -> warm-start，再被下一次工作验证。");
  const steps = [
    ["01", "Capture", "hook 极轻，只落原始事件"],
    ["02", "Replay", "沙箱重放，验证能跑"],
    ["03", "Output Gate", "看属性，不拿 baseline 强行对齐"],
    ["04", "Contract", "抽 I/O、目的、branch、behavior"],
    ["05", "三选一", "新工具 / 新分支 / 分支迭代"],
    ["06", "Composer", "组织变体，不洗掉年轮"],
    ["07", "Warm-start", "下次先复用，再决定要不要重写"],
  ];
  const startX = 72;
  const boxW = 145;
  const gap = 18;
  steps.forEach((step, idx) => {
    const x = startX + idx * (boxW + gap);
    addBox(slide, {
      left: x,
      top: 244,
      width: boxW,
      height: 208,
      fill: idx % 2 === 0 ? COLORS.paper : COLORS.tealSoft,
      lineFill: idx % 2 === 0 ? COLORS.line : COLORS.tealSoft,
      lineWidth: idx % 2 === 0 ? 1 : 0,
      radius: "rounded-3xl",
      shadow: "shadow-sm",
    });
    addText(slide, {
      left: x + 16,
      top: 262,
      width: 60,
      height: 24,
      text: step[0],
      fontSize: 18,
      color: COLORS.accent,
      bold: true,
    });
    addText(slide, {
      left: x + 16,
      top: 298,
      width: boxW - 32,
      height: 58,
      text: step[1],
      fontSize: 22,
      color: COLORS.ink,
      bold: true,
    });
    addText(slide, {
      left: x + 16,
      top: 360,
      width: boxW - 32,
      height: 72,
      text: step[2],
      fontSize: 15,
      color: COLORS.muted,
    });
    if (idx < steps.length - 1) {
      addText(slide, {
        left: x + boxW + 2,
        top: 330,
        width: 20,
        height: 20,
        text: "→",
        fontSize: 22,
        color: COLORS.muted,
        bold: true,
        align: "center",
      });
    }
  });
  addText(slide, {
    left: 72,
    top: 492,
    width: 1090,
    height: 60,
    text: "关键差异在中间两刀：Output Gate 只判输出属性达不达标，Composer 只组织变体、不消灭变体。这样才能保住 `_repair_*`、fallback、branch scars 这些真价值。",
    fontSize: 18,
    color: COLORS.ink,
  });
}

function buildSlide6(slide) {
  addSlideChrome(slide, 6, 12);
  addTitle(slide, "参考谁，但在哪一刀分道", "Yunjue 给骨架，Letta 给 manifest 直觉，MCP 给执行面；真正自己做的是“组织变体而不是洗掉变体”。");

  const rows = [
    ["Yunjue-Agent", "create / verify / reuse / absorb / generalize 的生命周期；R_miss；批量演化", "把 Merger 改成 Composer：我们不追求 canonical，小伤疤也要保住"],
    ["Letta / MemFS", "manifest 分层、git versioning、渐进披露", "manifest 由带外 daemon 写，不让 agent 自己维护记忆文件"],
    ["MCP", "统一执行接口、统一调用入口、统一工具暴露方式", "MCP 不是宿主体验层；promoted 也不等于 exposed"],
    ["doc2md", "真实终态尺子：一个目的、多分支、共享后处理、lineage", "它不是 demo，而是决定我们该怎么定义“成熟工具”"],
  ];
  const y0 = 188;
  rows.forEach((row, idx) => {
    const y = y0 + idx * 98;
    addBox(slide, {
      left: 72,
      top: y,
      width: 220,
      height: 80,
      fill: idx % 2 === 0 ? COLORS.paper : "#F2E8E0",
      lineFill: COLORS.line,
      lineWidth: 1,
      radius: "rounded-2xl",
      shadow: "none",
    });
    addText(slide, {
      left: 92,
      top: y + 20,
      width: 180,
      height: 38,
      text: row[0],
      fontSize: 21,
      color: COLORS.ink,
      bold: true,
    });
    addBox(slide, {
      left: 314,
      top: y,
      width: 344,
      height: 80,
      fill: COLORS.paper,
      lineFill: COLORS.line,
      lineWidth: 1,
      radius: "rounded-2xl",
      shadow: "none",
    });
    addText(slide, {
      left: 334,
      top: y + 14,
      width: 304,
      height: 52,
      text: row[1],
      fontSize: 16,
      color: COLORS.muted,
      bold: false,
    });
    addBox(slide, {
      left: 680,
      top: y,
      width: 458,
      height: 80,
      fill: idx % 2 === 0 ? COLORS.tealSoft : COLORS.accentSoft,
      lineFill: idx % 2 === 0 ? COLORS.tealSoft : COLORS.accentSoft,
      lineWidth: 0,
      radius: "rounded-2xl",
      shadow: "none",
    });
    addText(slide, {
      left: 700,
      top: y + 14,
      width: 418,
      height: 52,
      text: row[2],
      fontSize: 16,
      color: COLORS.ink,
      bold: true,
    });
  });
}

function buildSlide7(slide) {
  addSlideChrome(slide, 7, 12);
  addTitle(slide, "个人外挂只是起点，终局是项目组手艺网", "同一套引擎在不同作用域下，关心的不是同一件事。");
  const columns = [
    {
      title: "个人模式",
      fill: COLORS.paper,
      tag: "先跑通一个人",
      points: [
        "本地 sidecar，优先无感、低摩擦、立刻见效",
        "候选能力先服务自己：先有用，再谈 shared 和规范化",
        "review 最小化，允许 provisional、shadow、保守默认",
      ],
    },
    {
      title: "团队模式",
      fill: COLORS.tealSoft,
      tag: "开始跨人复用",
      points: [
        "引入 shared fixtures、review queue、visibility 和 exposure gate",
        "promoted 变成团队资产，开始关心误召回、依赖、权限和责任边界",
        "pull 审查仍成立，但严重事故必须低噪声可见",
      ],
    },
    {
      title: "项目组模式",
      fill: COLORS.accentSoft,
      tag: "最终蒸馏的是项目组",
      points: [
        "多个团队共享一张能力网：相同目的合并，不同环境保留分支",
        "重点从“我能不能复用”转成“别人能不能安全复用”",
        "治理对象不再是脚本，而是成熟能力、shared steps 和 review policies",
      ],
    },
  ];
  columns.forEach((col, idx) => {
    const x = 72 + idx * 380;
    addBox(slide, {
      left: x,
      top: 190,
      width: 340,
      height: 378,
      fill: col.fill,
      lineFill: idx === 0 ? COLORS.line : col.fill,
      lineWidth: idx === 0 ? 1 : 0,
      radius: "rounded-3xl",
    });
    addTag(slide, col.tag, x + 22, 214, 170, idx === 0 ? "#EEE7DC" : COLORS.paper, idx === 2 ? COLORS.danger : COLORS.teal);
    addText(slide, {
      left: x + 22,
      top: 264,
      width: 280,
      height: 42,
      text: col.title,
      fontSize: 26,
      color: COLORS.ink,
      bold: true,
    });
    addBulletList(slide, col.points, x + 22, 326, 286, 64, 17, COLORS.ink);
  });
}

function buildSlide8(slide) {
  addSlideChrome(slide, 8, 12);
  addTitle(slide, "审查是 pull，但影响前台的动作必须有门槛", "机器先整理证据，人只裁决归类、晋升、暴露和回滚。");
  addBox(slide, {
    left: 72,
    top: 194,
    width: 494,
    height: 332,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addTag(slide, "machine lane", 102, 218, 120, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 102,
    top: 268,
    width: 390,
    height: 52,
    text: "自动部分负责把证据整理成一个 ReviewItem，而不是把人重新丢回完整项目里。",
    fontSize: 22,
    color: COLORS.ink,
    bold: true,
  });
  addBulletList(slide, [
    "Gate 结果：能不能跑、输出达不达标、契约抽得清不清",
    "比较结果：和已有 branch / baseline / R_miss 的关系",
    "默认安全态：stable_active 不轻易替换，疑似误合并先 freeze 影响面",
  ], 102, 346, 390, 44, 17, COLORS.muted);

  addBox(slide, {
    left: 608,
    top: 194,
    width: 520,
    height: 332,
    fill: COLORS.darkPanel,
    lineFill: COLORS.darkPanel,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "human lane", 638, 218, 108, "#3A322C", "#F1D0AD");
  addText(slide, {
    left: 638,
    top: 268,
    width: 424,
    height: 52,
    text: "人工不是重跑测试，而是决定这个东西该以什么身份进入能力库。",
    fontSize: 22,
    color: "#FFFFFF",
    bold: true,
  });
  addBulletList(slide, [
    "approve-new-skill / approve-new-branch / approve-iteration",
    "keep-fallback / pin-path-b / expose / unexpose / rollback-review",
    "所有动作写 lineage，走原子写和 reconcile，不允许直接改 manifest 了事",
  ], 638, 348, 404, 46, 17, "#E7E5E4");
  addText(slide, {
    left: 72,
    top: 560,
    width: 1040,
    height: 30,
    text: "一句话：待审不阻塞采集和分析，但可以阻塞 promoted -> exposed、shared_post_processing 提升、团队发布。",
    fontSize: 18,
    color: COLORS.ink,
    bold: true,
  });
}

function buildSlide9(slide) {
  addSlideChrome(slide, 9, 12);
  addTitle(slide, "运维层：三进程、断点续接、低摩擦不是锦上添花，是命门", "系统如果会拖前台后腿，就永远不会真的被长期打开。");

  const x = 86;
  const boxW = 280;
  [
    ["Capture Hook", "CC 内唯一同步点\nappend-only / <5ms / 静默失败", COLORS.paper],
    ["Distiller Daemon", "空闲触发 / 批处理 / Replay + Gate + Composer", COLORS.tealSoft],
    ["MCP Server", "统一执行面 / warm-start 入口 / exposed tool gate", COLORS.accentSoft],
  ].forEach((proc, idx) => {
    addBox(slide, {
      left: x + idx * 348,
      top: 232,
      width: boxW,
      height: 168,
      fill: proc[2],
      lineFill: proc[2] === COLORS.paper ? COLORS.line : proc[2],
      lineWidth: proc[2] === COLORS.paper ? 1 : 0,
      radius: "rounded-3xl",
    });
    addText(slide, {
      left: x + 18 + idx * 348,
      top: 258,
      width: boxW - 36,
      height: 34,
      text: proc[0],
      fontSize: 28,
      color: COLORS.ink,
      bold: true,
      align: "center",
    });
    addText(slide, {
      left: x + 22 + idx * 348,
      top: 310,
      width: boxW - 44,
      height: 62,
      text: proc[1],
      fontSize: 18,
      color: COLORS.muted,
      bold: false,
      align: "center",
    });
    if (idx < 2) {
      addText(slide, {
        left: x + 296 + idx * 348,
        top: 306,
        width: 48,
        height: 22,
        text: "→",
        fontSize: 28,
        color: COLORS.muted,
        bold: true,
        align: "center",
      });
    }
  });

  addBulletList(slide, [
    "断点续接：processing_stage、幂等阶段、原子写、crash 后可续",
    "默认零配置：judge 优先复用现有凭证；疑难再升级模型档位",
    "可观测：queue depth、capture drop、retry、dead-letter、health status 都得能看见",
  ], 102, 454, 980, 42, 18, COLORS.ink);
}

function buildSlide10(slide) {
  addSlideChrome(slide, 10, 12);
  addTitle(slide, "价值怎么讲：先用预演口径证明方向", "以下数字按“文档转 markdown”场景做内部推演，用来讨论优先级，不是假装已经真实压测。");

  addBox(slide, {
    left: 72,
    top: 190,
    width: 654,
    height: 376,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  slide.charts.add("bar", {
    position: { left: 106, top: 248, width: 580, height: 250 },
    categories: ["无蒸馏", "个人模式", "团队模式"],
    series: [{ name: "每人每周少重写小时数", values: [0.4, 2.3, 5.1], fill: COLORS.accent }],
    hasLegend: false,
    dataLabels: { showValue: true, position: "outEnd" },
    yAxis: {
      majorGridlines: { style: "solid", fill: COLORS.line, width: 1 },
    },
  });
  addText(slide, {
    left: 106,
    top: 212,
    width: 430,
    height: 24,
    text: "预演口径：同一项目组内的文档处理和杂活脚本场景",
    fontSize: 14,
    color: COLORS.muted,
  });

  addNumberedStrip(slide, 764, 198, 392, 98, 1, "能力种子", "MVP 成功线不是做出“完美 doc2md”，而是从 trace 里长出 1 个带 3 个纯 Python 分支的能力种子。", COLORS.tealSoft);
  addNumberedStrip(slide, 764, 316, 392, 98, 2, "真实信号", "最重要的不是沉淀量，而是 warm-start 命中后大家直接复用，不再重写。", COLORS.accentSoft);
  addNumberedStrip(slide, 764, 434, 392, 98, 3, "组织价值", "进入团队 / 项目组后，节省的不只是脚本时间，更是交接、review、回退和踩坑成本。", "#EFE7DB");
}

function buildSlide11(slide) {
  addSlideChrome(slide, 11, 12);
  addTitle(slide, "90 天路线图：先跑通一个目的，再放大作用域", "MVP 要诚实，团队版才值得真正加固。");

  const phases = [
    ["0-30 天", "单人 MVP", [
      "只做 Claude Code + 文档转 markdown",
      "只自动转正纯 Python / 无系统依赖分支",
      "跑通 capture -> replay -> output gate -> contract -> warm-start",
    ]],
    ["30-60 天", "团队 alpha", [
      "加 review queue、visibility、shared fixtures、exposure gate",
      "开始区分 promoted / exposed / team-published",
      "把个人外挂变成小团队共享外挂",
    ]],
    ["60-90 天", "项目组 beta", [
      "把多个团队的同目的能力收敛成项目组手艺网",
      "引入更严格的 health、GC、权限与回滚策略",
      "把“有人会做”真正变成“组织会做”",
    ]],
  ];

  phases.forEach((phase, idx) => {
    const x = 72 + idx * 364;
    addBox(slide, {
      left: x,
      top: 208,
      width: 328,
      height: 356,
      fill: idx === 0 ? COLORS.paper : idx === 1 ? COLORS.tealSoft : COLORS.accentSoft,
      lineFill: idx === 0 ? COLORS.line : idx === 1 ? COLORS.tealSoft : COLORS.accentSoft,
      lineWidth: idx === 0 ? 1 : 0,
      radius: "rounded-3xl",
    });
    addText(slide, {
      left: x + 22,
      top: 232,
      width: 110,
      height: 24,
      text: phase[0],
      fontSize: 15,
      color: COLORS.accent,
      bold: true,
    });
    addText(slide, {
      left: x + 22,
      top: 270,
      width: 240,
      height: 42,
      text: phase[1],
      fontSize: 28,
      color: COLORS.ink,
      bold: true,
    });
    addBulletList(slide, phase[2], x + 22, 336, 274, 62, 18, COLORS.ink);
  });
}

function buildSlide12(slide) {
  addSlideChrome(slide, 12, 12);
  addTag(slide, "closing view", 72, 92, 120, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 72,
    top: 156,
    width: 760,
    height: 170,
    text: "先把一个目的炼成熟路，\n再把整个项目组炼成会做事的网。",
    fontSize: 50,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 72,
    top: 362,
    width: 760,
    height: 108,
    text: "如果这个方向成立，蒸馏器最终沉淀的就不是某个人的脚本集合，而是整个项目组在真实工作里慢慢长出来的手艺资产。",
    fontSize: 24,
    color: COLORS.muted,
  });
  addBox(slide, {
    left: 832,
    top: 152,
    width: 330,
    height: 344,
    fill: COLORS.darkPanel,
    lineFill: COLORS.darkPanel,
    lineWidth: 0,
    radius: "rounded-3xl",
    shadow: "shadow-md",
  });
  addText(slide, {
    left: 862,
    top: 190,
    width: 246,
    height: 28,
    text: "这版 deck 的目标",
    fontSize: 16,
    color: "#E7E5E4",
    bold: true,
  });
  addBulletList(slide, [
    "统一内部叙事：不是知识库，是手艺沉淀与回灌",
    "确认第一条可跑通的目的：文档转 markdown",
    "确认扩展方向：个人 -> 团队 -> 项目组",
    "确认门槛：无感、可回退、保年轮、先复用后重写",
  ], 862, 244, 246, 56, 17, "#FFFFFF");
  addText(slide, {
    left: 72,
    top: 544,
    width: 690,
    height: 52,
    text: "内部一句话：把社畜拿命试出来的活路，精细蒸馏成新人和 agent 都能复用的熟路。",
    fontSize: 20,
    color: COLORS.accent,
    bold: true,
  });
}

async function main() {
  const finalPptx = process.env.FINAL_PPTX;
  const tmpDir = process.env.TMP_DIR;
  if (!finalPptx || !tmpDir) {
    throw new Error("FINAL_PPTX and TMP_DIR are required.");
  }

  const previewDir = path.join(tmpDir, "preview");
  const layoutDir = path.join(tmpDir, "layout");
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });

  await fs.writeFile(
    path.join(tmpDir, "source-notes.txt"),
    [
      "Deck topic: 手艺人蒸馏器 internal pre deck",
      "Primary sources:",
      "- D:/interact/员工蒸馏器-设计文档-v0.4.md",
      "- D:/interact/员工蒸馏器-契约引擎设计.md",
      "- D:/interact/员工蒸馏器-运维层.md",
      "- D:/interact/员工蒸馏器-观测与审查层.md",
      "",
      "Notes:",
      "- This deck is an internal pre-read, not an external investor deck.",
      "- Some metrics are intentionally presented as scenario estimates for discussion, not as real benchmark data.",
      "- doc2md is used as the explanatory sample because the current design explicitly reverse-engineers from it.",
    ].join("\n"),
    "utf8",
  );

  const presentation = Presentation.create({
    slideSize: { width: SLIDE_W, height: SLIDE_H },
  });

  const builders = [
    buildSlide1,
    buildSlide2,
    buildSlide3,
    buildSlide4,
    buildSlide5,
    buildSlide6,
    buildSlide7,
    buildSlide8,
    buildSlide9,
    buildSlide10,
    buildSlide11,
    buildSlide12,
  ];

  for (const build of builders) {
    const slide = presentation.slides.add();
    build(slide);
  }

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(
      path.join(previewDir, `${stem}.png`),
      await presentation.export({ slide, format: "png", scale: 1 }),
    );
    await fs.writeFile(
      path.join(layoutDir, `${stem}.layout.json`),
      await (await slide.export({ format: "layout" })).text(),
      "utf8",
    );
  }

  await writeBlob(
    path.join(tmpDir, "deck-montage.webp"),
    await presentation.export({ format: "webp", montage: true, scale: 1 }),
  );

  const pptx = await PresentationFile.exportPptx(presentation);
  await fs.mkdir(path.dirname(finalPptx), { recursive: true });
  await pptx.save(finalPptx);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
