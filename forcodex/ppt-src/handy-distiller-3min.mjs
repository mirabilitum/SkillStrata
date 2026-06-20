import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const SLIDE_W = 1280;
const SLIDE_H = 720;

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
    position: { left: 1010, top: -160, width: 380, height: 380 },
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
    width: 280,
    height: 18,
    text: "手艺人蒸馏器 xs / 3 min internal pre",
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
    left: 72,
    top: 64,
    width: 980,
    height: 56,
    text: title,
    fontSize: 35,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 72,
    top: 116,
    width: 940,
    height: 32,
    text: subtitle,
    fontSize: 18,
    color: COLORS.muted,
  });
}

function addBullets(slide, items, left, top, width, lineGap = 46, fontSize = 20, color = COLORS.ink) {
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
  addChrome(slide, 1, 4);
  addTag(slide, "3 分钟版 / 内部预演", 72, 92, 170);
  addText(slide, {
    left: 72,
    top: 152,
    width: 660,
    height: 80,
    text: "手艺人蒸馏器",
    fontSize: 58,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 72,
    top: 262,
    width: 690,
    height: 82,
    text: "把社畜踩出来的活路，炼成下次不用重写的工具、熟路和团队资产。",
    fontSize: 28,
    color: COLORS.muted,
  });
  addText(slide, {
    left: 72,
    top: 446,
    width: 590,
    height: 30,
    text: "今天只讲：一个例子、它为什么值得做、终局长什么样。",
    fontSize: 20,
    color: COLORS.ink,
  });

  addBox(slide, {
    left: 826,
    top: 158,
    width: 332,
    height: 314,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
    shadow: "shadow-md",
  });
  addText(slide, {
    left: 854,
    top: 194,
    width: 220,
    height: 24,
    text: "今天就 3 句话",
    fontSize: 17,
    color: "#E7E5E4",
    bold: true,
  });
  addBullets(slide, [
    "杂活永远有人做，但总是很难留下来",
    "蒸馏器保存的不是文档，而是“这套做法”",
    "终局不是个人外挂，而是项目组熟路网",
  ], 854, 246, 226, 60, 23, "#FFFFFF");
}

function slide2(slide) {
  addChrome(slide, 2, 4);
  addTitle(slide, "先看一个大家都懂的杂活", "把一堆文档整理成能喂给 LLM 的 Markdown。");

  addBox(slide, {
    left: 72,
    top: 188,
    width: 328,
    height: 334,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addTag(slide, "任务开场", 96, 212, 82, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 96,
    top: 258,
    width: 220,
    height: 38,
    text: "新人接手资料包",
    fontSize: 28,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "pdf、docx、xlsx 混在一起",
    "图片散在子目录里",
    "今晚前要给 agent 一份可用 md 语料",
  ], 96, 328, 240, 58, 18, COLORS.ink);

  addText(slide, {
    left: 418,
    top: 336,
    width: 42,
    height: 24,
    text: "→",
    fontSize: 34,
    color: COLORS.accent,
    bold: true,
    align: "center",
  });

  addBox(slide, {
    left: 488,
    top: 188,
    width: 312,
    height: 334,
    fill: COLORS.tealSoft,
    lineFill: COLORS.tealSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "于是开始手搓", 512, 212, 114, COLORS.paper, COLORS.teal);
  addBullets(slide, [
    "先扫目录，再补 pdf / docx 分支",
    "路径、图片、表格一坏就加 repair",
    "实在不行就 fallback 到通用库",
  ], 512, 286, 240, 62, 18, COLORS.ink);

  addText(slide, {
    left: 820,
    top: 336,
    width: 42,
    height: 24,
    text: "→",
    fontSize: 34,
    color: COLORS.accent,
    bold: true,
    align: "center",
  });

  addBox(slide, {
    left: 892,
    top: 188,
    width: 288,
    height: 334,
    fill: COLORS.accentSoft,
    lineFill: COLORS.accentSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "一周后", 916, 212, 74, COLORS.paper, COLORS.accent);
  addBullets(slide, [
    "脚本还在，但只有自己看得懂",
    "别人接手还是会从头再搓一版",
    "agent 下次遇到类似任务，也继续假装第一次见",
  ], 916, 286, 214, 64, 18, COLORS.ink);

  addText(slide, {
    left: 72,
    top: 566,
    width: 1050,
    height: 28,
    text: "所以蒸馏器瞄准的不是“把文档转成 md”，而是“把这套做法留下来”。",
    fontSize: 22,
    color: COLORS.accent,
    bold: true,
  });
}

function slide3(slide) {
  addChrome(slide, 3, 4);
  addTitle(slide, "拿 doc2md 来看，年轮其实是看得见的", "不是抽象“迭代”，而是代码里真实长出来的分支、repair、fallback 和 shared step。");

  addBox(slide, {
    left: 72,
    top: 170,
    width: 1136,
    height: 84,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
    shadow: "shadow-md",
  });
  addText(slide, {
    left: 104,
    top: 186,
    width: 280,
    height: 26,
    text: "doc2md = 一个目的：",
    fontSize: 23,
    color: "#FFFFFF",
    bold: true,
  });
  addText(slide, {
    left: 104,
    top: 214,
    width: 360,
    height: 30,
    text: "任意文档 -> Markdown",
    fontSize: 23,
    color: "#FFFFFF",
    bold: true,
  });
  addText(slide, {
    left: 472,
    top: 206,
    width: 620,
    height: 24,
    text: "所以 pdf / docx / xlsx / pptx 不该拆成五个小工具，而是同一目的下不断长出来的几圈年轮。",
    fontSize: 16,
    color: "#E7E5E4",
  });

  const rings = [
    ["第 1 圈", "先长分支", "suffix 分流\npdf / docx / xlsx / pptx", COLORS.paper],
    ["第 2 圈", "补坏样本", "扫描 PDF -> scanned\n坏 docx -> relationship repair", COLORS.tealSoft],
    ["第 3 圈", "挂通用兜底", "兜不住的格式\n走 generic / markitdown", COLORS.accentSoft],
    ["第 4 圈", "提共享后处理", "最后收敛出\nsanitize_text / table_to_list", COLORS.sand],
  ];

  rings.forEach((ring, idx) => {
    const x = 72 + idx * 288;
    addBox(slide, {
      left: x,
      top: 286,
      width: 248,
      height: 196,
      fill: ring[3],
      lineFill: ring[3] === COLORS.paper ? COLORS.line : ring[3],
      lineWidth: ring[3] === COLORS.paper ? 1 : 0,
      radius: "rounded-3xl",
    });
    addTag(slide, ring[0], x + 20, 306, 76, COLORS.paper, COLORS.muted);
    addText(slide, {
      left: x + 20,
      top: 350,
      width: 180,
      height: 34,
      text: ring[1],
      fontSize: 26,
      color: COLORS.ink,
      bold: true,
    });
    addText(slide, {
      left: x + 20,
      top: 398,
      width: 204,
      height: 58,
      text: ring[2],
      fontSize: 17,
      color: COLORS.muted,
    });
    if (idx < rings.length - 1) {
      addText(slide, {
        left: x + 252,
        top: 370,
        width: 28,
        height: 24,
        text: "→",
        fontSize: 28,
        color: COLORS.accent,
        bold: true,
        align: "center",
      });
    }
  });

  addBox(slide, {
    left: 72,
    top: 516,
    width: 1136,
    height: 112,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 100,
    top: 536,
    width: 520,
    height: 50,
    text: "这就是“年轮”在代码里的样子：新增分支、补伤疤、挂 fallback、再把通用处理提成 shared。",
    fontSize: 18,
    color: "#FFFFFF",
    bold: true,
  });
  addText(slide, {
    left: 100,
    top: 589,
    width: 380,
    height: 18,
    text: "然后在设计 md 里，再把这些变化记成 iteration_log。",
    fontSize: 15,
    color: "#D6D3D1",
  });

  addBox(slide, {
    left: 692,
    top: 536,
    width: 430,
    height: 72,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-2xl",
    shadow: "none",
  });
  addText(slide, {
    left: 714,
    top: 552,
    width: 384,
    height: 18,
    text: "ver: 3  branch: docx   add _repair_docx_relationships",
    fontSize: 14,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 714,
    top: 580,
    width: 360,
    height: 18,
    text: "ver: 4  scope: shared add table_to_list",
    fontSize: 14,
    color: COLORS.ink,
    bold: true,
  });
}

function slide4(slide) {
  addChrome(slide, 4, 4);
  addTitle(slide, "愿景、技术栈和预期效果", "先帮一个人少重写，最后服务整个项目组；技术栈只要够小够诚实。");

  addBox(slide, {
    left: 72,
    top: 188,
    width: 470,
    height: 330,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 96,
    top: 214,
    width: 200,
    height: 32,
    text: "愿景",
    fontSize: 28,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "个人模式：先让自己少重写一类杂活",
    "团队模式：promoted 开始变成团队资产",
    "项目组模式：相同目的合并，不同环境保留分支",
  ], 96, 272, 372, 62, 19, COLORS.ink);

  addBox(slide, {
    left: 572,
    top: 188,
    width: 260,
    height: 330,
    fill: COLORS.tealSoft,
    lineFill: COLORS.tealSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 598,
    top: 214,
    width: 170,
    height: 32,
    text: "最小技术栈",
    fontSize: 28,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "Capture Hook",
    "Distiller Daemon",
    "MCP Sidecar",
    "唯一像前台的可能是 review queue",
  ], 598, 274, 180, 50, 18, COLORS.ink);

  addBox(slide, {
    left: 862,
    top: 188,
    width: 294,
    height: 330,
    fill: COLORS.accentSoft,
    lineFill: COLORS.accentSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 888,
    top: 214,
    width: 190,
    height: 32,
    text: "预期效果",
    fontSize: 28,
    color: COLORS.ink,
    bold: true,
  });
  slide.charts.add("bar", {
    position: { left: 904, top: 270, width: 190, height: 150 },
    categories: ["无蒸馏", "个人", "团队"],
    series: [{ name: "每周少重写小时数", values: [0.5, 2.2, 5.0], fill: COLORS.accent }],
    hasLegend: false,
    dataLabels: { showValue: true, position: "outEnd" },
    yAxis: {
      majorGridlines: { style: "solid", fill: COLORS.line, width: 1 },
    },
  });
  addText(slide, {
    left: 888,
    top: 444,
    width: 208,
    height: 44,
    text: "内部预演口径，不是假装已经跑完真实 benchmark。",
    fontSize: 16,
    color: COLORS.ink,
  });
}

async function main() {
  const finalPptx = process.env.FINAL_PPTX;
  const tmpDir = process.env.TMP_DIR;
  if (!finalPptx || !tmpDir) {
    throw new Error("FINAL_PPTX and TMP_DIR are required.");
  }

  const previewDir = path.join(tmpDir, "preview-3min");
  const layoutDir = path.join(tmpDir, "layout-3min");
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });

  await fs.writeFile(
    path.join(tmpDir, "source-notes-3min.txt"),
    [
      "Deck topic: 手艺人蒸馏器 3-minute internal pre deck",
      "Primary sources:",
      "- D:/interact/员工蒸馏器-设计文档-v0.4.md",
      "- D:/interact/员工蒸馏器-契约引擎设计.md",
      "- D:/interact/员工蒸馏器-运维层.md",
      "- D:/interact/员工蒸馏器-观测与审查层.md",
      "",
      "Notes:",
      "- 4-slide example-first deck for a 3-minute internal talk.",
      "- Uses doc2md as the main explanatory sample.",
      "- Forecast numbers are scenario estimates, not benchmark claims.",
    ].join("\n"),
    "utf8",
  );

  const presentation = Presentation.create({
    slideSize: { width: SLIDE_W, height: SLIDE_H },
  });

  const builders = [slide1, slide2, slide3, slide4];
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
    path.join(tmpDir, "deck-montage-3min.webp"),
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
