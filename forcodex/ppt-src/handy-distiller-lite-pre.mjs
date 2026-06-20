import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const SLIDE_W = 1280;
const SLIDE_H = 720;
const FRAME = { left: 72, top: 64, width: 1136, height: 592 };

const COLORS = {
  bg: "#F6F1E8",
  paper: "#FFFDF8",
  ink: "#171717",
  muted: "#57534E",
  line: "#D8CDBE",
  accent: "#C96A1B",
  accentSoft: "#F2DDC9",
  teal: "#0F766E",
  tealSoft: "#DDEFEA",
  sand: "#EDE4D7",
  dark: "#24211D",
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
  fill = "none",
  lineFill = "none",
  lineWidth = 0,
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
    color,
    bold,
    alignment: align,
  };
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
  radius = "rounded-2xl",
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

function addTag(slide, text, left, top, width = 180, fill = COLORS.accentSoft, color = COLORS.accent) {
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
    top: top + 8,
    width: width - 28,
    height: 18,
    text,
    fontSize: 12,
    color,
    bold: true,
  });
}

function addChrome(slide, index, total) {
  slide.background.fill = COLORS.bg;
  slide.shapes.add({
    geometry: "rect",
    position: { left: 0, top: 0, width: 24, height: SLIDE_H },
    fill: COLORS.accent,
    line: { style: "solid", fill: COLORS.accent, width: 0 },
  });
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: 1008, top: -170, width: 390, height: 390 },
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
    text: "手艺人蒸馏器 xs / light internal pre",
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
    width: 920,
    height: 56,
    text: title,
    fontSize: 35,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: FRAME.left,
    top: FRAME.top + 50,
    width: 900,
    height: 34,
    text: subtitle,
    fontSize: 18,
    color: COLORS.muted,
  });
}

function addBullets(slide, items, left, top, width, lineGap = 44, fontSize = 20, color = COLORS.ink) {
  items.forEach((item, index) => {
    addText(slide, {
      left,
      top: top + index * lineGap,
      width: 20,
      height: 20,
      text: "•",
      fontSize,
      color,
      bold: true,
    });
    addText(slide, {
      left: left + 22,
      top: top + index * lineGap,
      width: width - 22,
      height: lineGap,
      text: item,
      fontSize,
      color,
    });
  });
}

function slide1(slide) {
  addChrome(slide, 1, 8);
  addTag(slide, "内部预演 / 例子先行", 72, 92, 190);
  addText(slide, {
    left: 72,
    top: 146,
    width: 680,
    height: 84,
    text: "手艺人蒸馏器",
    fontSize: 58,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 72,
    top: 258,
    width: 690,
    height: 86,
    text: "把社畜踩出来的活路，炼成下次不用重写的工具、熟路和团队资产。",
    fontSize: 28,
    color: COLORS.muted,
  });
  addText(slide, {
    left: 72,
    top: 438,
    width: 570,
    height: 60,
    text: "这版故意不讲重架构，先用一个例子把“为什么值得做”讲顺。",
    fontSize: 18,
    color: COLORS.ink,
  });

  addBox(slide, {
    left: 822,
    top: 152,
    width: 344,
    height: 334,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
    shadow: "shadow-md",
  });
  addText(slide, {
    left: 852,
    top: 190,
    width: 250,
    height: 24,
    text: "今天就讲四件事",
    fontSize: 16,
    color: "#E7E5E4",
    bold: true,
  });
  addBullets(slide, [
    "一个杂活例子",
    "为什么它值得做成系统",
    "终局长什么样",
    "技术栈和预期效果",
  ], 852, 244, 250, 60, 24, "#FFFFFF");
}

function slide2(slide) {
  addChrome(slide, 2, 8);
  addTitle(slide, "先看一个大家都懂的杂活", "把一堆文档整理成能喂给 LLM 的 Markdown。");

  addBox(slide, {
    left: 72,
    top: 182,
    width: 320,
    height: 352,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addTag(slide, "真实任务开场", 96, 206, 108, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 96,
    top: 258,
    width: 240,
    height: 38,
    text: "新人接手资料包",
    fontSize: 28,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "47 个 pdf，12 个 docx，6 个 xlsx",
    "图片散在子目录里，文件名一团糟",
    "今晚前要给 agent 一份可用 md 语料",
  ], 96, 320, 240, 54, 18, COLORS.ink);

  addText(slide, {
    left: 418,
    top: 332,
    width: 52,
    height: 24,
    text: "→",
    fontSize: 34,
    color: COLORS.accent,
    bold: true,
    align: "center",
  });

  addBox(slide, {
    left: 498,
    top: 182,
    width: 292,
    height: 352,
    fill: COLORS.tealSoft,
    lineFill: COLORS.tealSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "于是开始手搓", 522, 206, 112, COLORS.paper, COLORS.teal);
  addBullets(slide, [
    "先写一个临时脚本把文件全扫一遍",
    "pdf 和 docx 分别补分支",
    "路径、图片、表格一坏就加 repair",
    "不行再 fallback 到通用库",
  ], 522, 268, 220, 58, 18, COLORS.ink);

  addText(slide, {
    left: 812,
    top: 332,
    width: 52,
    height: 24,
    text: "→",
    fontSize: 34,
    color: COLORS.accent,
    bold: true,
    align: "center",
  });

  addBox(slide, {
    left: 892,
    top: 182,
    width: 288,
    height: 352,
    fill: COLORS.accentSoft,
    lineFill: COLORS.accentSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "一周后", 916, 206, 74, COLORS.paper, COLORS.accent);
  addBullets(slide, [
    "脚本还在，但只有自己看得懂",
    "别人接手还是会从头再搓一版",
    "agent 下次遇到类似任务，也继续假装第一次见",
  ], 916, 268, 214, 64, 18, COLORS.ink);

  addText(slide, {
    left: 72,
    top: 572,
    width: 1040,
    height: 24,
    text: "这就是蒸馏器瞄准的目标：不是把文档转成 md，而是把“这套做法”留下来。",
    fontSize: 20,
    color: COLORS.accent,
    bold: true,
  });
}

function slide3(slide) {
  addChrome(slide, 3, 8);
  addTitle(slide, "为什么非做不可", "因为这种杂活不是没人会做，而是永远没人真正记住怎么做。");

  const items = [
    {
      n: "01",
      title: "写过，但找不到",
      body: "临时脚本和补丁常常只活在某次会话或某个临时目录里。",
      fill: COLORS.paper,
    },
    {
      n: "02",
      title: "交结果，不交手法",
      body: "新人拿到的是一份 md，拿不到为什么这么切分、坏了怎么回退。",
      fill: COLORS.tealSoft,
    },
    {
      n: "03",
      title: "agent 每次从零假装聪明",
      body: "没有 reuse-before-create，就只能继续重写同类工具。",
      fill: COLORS.accentSoft,
    },
  ];

  items.forEach((item, idx) => {
    const x = 72 + idx * 360;
    addBox(slide, {
      left: x,
      top: 224,
      width: 320,
      height: 262,
      fill: item.fill,
      lineFill: item.fill === COLORS.paper ? COLORS.line : item.fill,
      lineWidth: item.fill === COLORS.paper ? 1 : 0,
      radius: "rounded-3xl",
    });
    addText(slide, {
      left: x + 24,
      top: 246,
      width: 50,
      height: 24,
      text: item.n,
      fontSize: 22,
      color: COLORS.accent,
      bold: true,
    });
    addText(slide, {
      left: x + 24,
      top: 290,
      width: 230,
      height: 42,
      text: item.title,
      fontSize: 28,
      color: COLORS.ink,
      bold: true,
    });
    addText(slide, {
      left: x + 24,
      top: 356,
      width: 250,
      height: 92,
      text: item.body,
      fontSize: 19,
      color: COLORS.muted,
    });
  });

  addText(slide, {
    left: 72,
    top: 544,
    width: 1060,
    height: 46,
    text: "说白了，蒸馏器要保存的不是“代码文件”，而是踩坑踩出来的判断、分支、fallback 和伤疤。",
    fontSize: 22,
    color: COLORS.ink,
    bold: true,
  });
}

function slide4(slide) {
  addChrome(slide, 4, 8);
  addTitle(slide, "它真正做的事其实很朴素", "先看见重复，再抽成候选，再验证，最后在下次任务前把成熟做法递回来。");

  const steps = [
    ["看到", "从真实工作里看到反复出现的脚本和 repair"],
    ["抽出", "把它们按“目的 / 契约 / 分支”组织成候选能力"],
    ["验证", "跑 Replay、Output Gate、Contract，而不是只看它能不能运行"],
    ["回灌", "下次同类任务先把现成能力拿出来，再决定要不要重写"],
  ];

  steps.forEach((step, idx) => {
    const x = 72 + idx * 268;
    addBox(slide, {
      left: x,
      top: 214,
      width: 238,
      height: 178,
      fill: idx % 2 === 0 ? COLORS.paper : COLORS.tealSoft,
      lineFill: idx % 2 === 0 ? COLORS.line : COLORS.tealSoft,
      lineWidth: idx % 2 === 0 ? 1 : 0,
      radius: "rounded-3xl",
    });
    addText(slide, {
      left: x + 20,
      top: 238,
      width: 44,
      height: 24,
      text: String(idx + 1).padStart(2, "0"),
      fontSize: 20,
      color: COLORS.accent,
      bold: true,
    });
    addText(slide, {
      left: x + 20,
      top: 280,
      width: 180,
      height: 34,
      text: step[0],
      fontSize: 28,
      color: COLORS.ink,
      bold: true,
    });
    addText(slide, {
      left: x + 20,
      top: 332,
      width: 188,
      height: 46,
      text: step[1],
      fontSize: 17,
      color: COLORS.muted,
    });
  });

  addBox(slide, {
    left: 118,
    top: 462,
    width: 1040,
    height: 82,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 150,
    top: 482,
    width: 972,
    height: 42,
    text: "用 `doc2md` 这件事来讲，就是：别把它拆成一堆小工具，而是让它长成一个“文档转 markdown”的成熟能力，里面保留 pdf / docx / xlsx / fallback 等分支和伤疤。",
    fontSize: 20,
    color: "#FFFFFF",
    bold: true,
  });
}

function slide5(slide) {
  addChrome(slide, 5, 8);
  addTitle(slide, "愿景：终局不是个人外挂，而是项目组熟路网", "同一套引擎先帮一个人，最后服务整个项目组。");

  const cols = [
    {
      title: "个人",
      tag: "先帮自己少重写",
      fill: COLORS.paper,
      bullets: [
        "先跑一个目的：文档转 markdown",
        "优先无感、低摩擦、立刻见效",
        "候选能力先服务自己",
      ],
    },
    {
      title: "团队",
      tag: "开始跨人复用",
      fill: COLORS.tealSoft,
      bullets: [
        "开始有 shared fixtures 和 review queue",
        "promoted 变成团队资产",
        "重点变成“别人能不能安全复用”",
      ],
    },
    {
      title: "项目组",
      tag: "最后蒸馏的是整组",
      fill: COLORS.accentSoft,
      bullets: [
        "多个团队共用一张能力网",
        "相同目的合并，不同环境保留分支",
        "手艺开始变成组织资产",
      ],
    },
  ];

  cols.forEach((col, idx) => {
    const x = 72 + idx * 380;
    addBox(slide, {
      left: x,
      top: 208,
      width: 340,
      height: 336,
      fill: col.fill,
      lineFill: col.fill === COLORS.paper ? COLORS.line : col.fill,
      lineWidth: col.fill === COLORS.paper ? 1 : 0,
      radius: "rounded-3xl",
    });
    addTag(slide, col.tag, x + 24, 232, 140, col.fill === COLORS.paper ? COLORS.sand : COLORS.paper, idx === 2 ? COLORS.accent : COLORS.teal);
    addText(slide, {
      left: x + 24,
      top: 286,
      width: 220,
      height: 36,
      text: `${col.title}模式`,
      fontSize: 30,
      color: COLORS.ink,
      bold: true,
    });
    addBullets(slide, col.bullets, x + 24, 350, 250, 58, 18, COLORS.ink);
  });
}

function slide6(slide) {
  addChrome(slide, 6, 8);
  addTitle(slide, "唯一长得像前台的地方，大概是审查台", "平时无感；真要看东西时，才 pull 出一个能做决定的界面。");

  addBox(slide, {
    left: 72,
    top: 188,
    width: 232,
    height: 370,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 96,
    top: 214,
    width: 120,
    height: 28,
    text: "待审队列",
    fontSize: 24,
    color: COLORS.ink,
    bold: true,
  });
  [
    "rev-014  ambiguous",
    "rev-015  path-b pin",
    "rev-016  expose check",
  ].forEach((row, idx) => {
    addBox(slide, {
      left: 96,
      top: 270 + idx * 90,
      width: 184,
      height: 64,
      fill: idx === 0 ? COLORS.tealSoft : idx === 1 ? COLORS.accentSoft : COLORS.sand,
      lineFill: "none",
      lineWidth: 0,
      radius: "rounded-2xl",
      shadow: "none",
    });
    addText(slide, {
      left: 110,
      top: 292 + idx * 90,
      width: 156,
      height: 22,
      text: row,
      fontSize: 16,
      color: COLORS.ink,
      bold: true,
    });
  });

  addBox(slide, {
    left: 338,
    top: 188,
    width: 474,
    height: 370,
    fill: COLORS.tealSoft,
    lineFill: COLORS.tealSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 366,
    top: 214,
    width: 180,
    height: 28,
    text: "证据和比较",
    fontSize: 24,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "系统建议：`same_purpose_new_branch`",
    "目标能力：`doc-to-markdown`",
    "旧分支：generic(markitdown fallback)",
    "新证据：保住了 xlsx sheet 名和图片引用",
    "风险：依赖更重，回归样本还不够",
  ], 366, 272, 388, 52, 18, COLORS.ink);
  addText(slide, {
    left: 366,
    top: 504,
    width: 388,
    height: 28,
    text: "这里才是人真正“看系统”的地方。",
    fontSize: 20,
    color: COLORS.accent,
    bold: true,
  });

  addBox(slide, {
    left: 846,
    top: 188,
    width: 310,
    height: 370,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 874,
    top: 214,
    width: 160,
    height: 28,
    text: "动作面板",
    fontSize: 24,
    color: "#FFFFFF",
    bold: true,
  });
  const actions = [
    { y: 274, text: "approve new branch", fill: "#F4D7B7", color: COLORS.ink },
    { y: 350, text: "keep provisional", fill: "#DDEFEA", color: COLORS.ink },
    { y: 426, text: "defer for more evidence", fill: "#EFE7DB", color: COLORS.ink },
  ];
  actions.forEach((action) => {
    addBox(slide, {
      left: 874,
      top: action.y,
      width: 220,
      height: 50,
      fill: action.fill,
      lineFill: action.fill,
      lineWidth: 0,
      radius: "rounded-full",
      shadow: "none",
    });
    addText(slide, {
      left: 894,
      top: action.y + 15,
      width: 180,
      height: 20,
      text: action.text,
      fontSize: 15,
      color: action.color,
      bold: true,
      align: "center",
    });
  });
  addText(slide, {
    left: 874,
    top: 502,
    width: 214,
    height: 34,
    text: "现在还没做，但未来最像“前台”的大概就这一页。",
    fontSize: 17,
    color: "#E7E5E4",
  });
}

function slide7(slide) {
  addChrome(slide, 7, 8);
  addTitle(slide, "技术栈和预期效果", "先用最小技术栈跑通，再用最朴素的效果预期判断值不值得放大。");

  const boxes = [
    ["Capture Hook", "极轻采集，只写原始事件", COLORS.paper],
    ["Distiller Daemon", "Replay / Gate / Contract / Composer", COLORS.tealSoft],
    ["MCP Sidecar", "统一调用入口 + warm-start 回灌", COLORS.accentSoft],
  ];
  boxes.forEach((box, idx) => {
    const x = 72 + idx * 248;
    addBox(slide, {
      left: x,
      top: 206,
      width: 220,
      height: 146,
      fill: box[2],
      lineFill: box[2] === COLORS.paper ? COLORS.line : box[2],
      lineWidth: box[2] === COLORS.paper ? 1 : 0,
      radius: "rounded-3xl",
    });
    addText(slide, {
      left: x + 18,
      top: 236,
      width: 184,
      height: 32,
      text: box[0],
      fontSize: 24,
      color: COLORS.ink,
      bold: true,
      align: "center",
    });
    addText(slide, {
      left: x + 18,
      top: 282,
      width: 184,
      height: 36,
      text: box[1],
      fontSize: 16,
      color: COLORS.muted,
      align: "center",
    });
  });

  addBox(slide, {
    left: 832,
    top: 188,
    width: 324,
    height: 378,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 860,
    top: 214,
    width: 210,
    height: 28,
    text: "内部预期效果",
    fontSize: 24,
    color: COLORS.ink,
    bold: true,
  });
  slide.charts.add("bar", {
    position: { left: 860, top: 270, width: 250, height: 190 },
    categories: ["无蒸馏", "个人", "团队"],
    series: [{ name: "每周少重写小时数", values: [0.5, 2.2, 5.0], fill: COLORS.accent }],
    hasLegend: false,
    dataLabels: { showValue: true, position: "outEnd" },
    yAxis: {
      majorGridlines: { style: "solid", fill: COLORS.line, width: 1 },
    },
  });
  addText(slide, {
    left: 860,
    top: 484,
    width: 232,
    height: 54,
    text: "这不是实测宣传数据，只是内部讨论优先级的预演口径。",
    fontSize: 16,
    color: COLORS.muted,
  });

  addText(slide, {
    left: 72,
    top: 418,
    width: 706,
    height: 28,
    text: "判断项目值不值得继续，不看“沉淀了多少”，主要看三件事：",
    fontSize: 20,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "warm-start 命中后，大家是不是真的直接复用",
    "候选能力能不能长成一个像 `doc2md` 那样的成熟目的",
    "团队接手时，是不是真的开始少踩一遍同样的坑",
  ], 72, 468, 670, 44, 18, COLORS.ink);
}

function slide8(slide) {
  addChrome(slide, 8, 8);
  addTag(slide, "closing", 72, 92, 92, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 72,
    top: 152,
    width: 820,
    height: 150,
    text: "先把一个目的炼成熟路，\n再把整个项目组炼成会做事的网。",
    fontSize: 50,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 72,
    top: 362,
    width: 710,
    height: 88,
    text: "如果这条路成立，手艺人蒸馏器最终沉淀的就不是某个人的脚本集合，而是整个项目组在真实工作里慢慢长出来的熟路资产。",
    fontSize: 24,
    color: COLORS.muted,
  });
  addBox(slide, {
    left: 838,
    top: 162,
    width: 320,
    height: 300,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 866,
    top: 196,
    width: 240,
    height: 24,
    text: "下一步只做三件事",
    fontSize: 18,
    color: "#E7E5E4",
    bold: true,
  });
  addBullets(slide, [
    "先把文档转 markdown 这一条路跑熟",
    "先拿到第一个真实 warm-start 命中",
    "再决定要不要加固到团队和项目组",
  ], 866, 248, 228, 58, 18, "#FFFFFF");
  addText(slide, {
    left: 72,
    top: 528,
    width: 760,
    height: 32,
    text: "内部一句话：把社畜踩出来的活路，精细蒸馏成下次不用重写的熟路。",
    fontSize: 21,
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

  const previewDir = path.join(tmpDir, "preview-lite");
  const layoutDir = path.join(tmpDir, "layout-lite");
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });

  await fs.writeFile(
    path.join(tmpDir, "source-notes-lite.txt"),
    [
      "Deck topic: 手艺人蒸馏器 lighter internal pre deck",
      "Primary sources:",
      "- D:/interact/员工蒸馏器-设计文档-v0.4.md",
      "- D:/interact/员工蒸馏器-契约引擎设计.md",
      "- D:/interact/员工蒸馏器-运维层.md",
      "- D:/interact/员工蒸馏器-观测与审查层.md",
      "",
      "Notes:",
      "- Example-first deck for internal discussion.",
      "- Uses doc2md as the concrete sample.",
      "- Forecast numbers are intentionally scenario estimates, not benchmark claims.",
    ].join("\n"),
    "utf8",
  );

  const presentation = Presentation.create({
    slideSize: { width: SLIDE_W, height: SLIDE_H },
  });

  const builders = [slide1, slide2, slide3, slide4, slide5, slide6, slide7, slide8];
  for (const builder of builders) {
    const slide = presentation.slides.add();
    builder(slide);
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
    path.join(tmpDir, "deck-montage-lite.webp"),
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
