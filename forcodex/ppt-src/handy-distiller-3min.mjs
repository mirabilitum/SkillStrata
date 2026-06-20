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
    width: 720,
    height: 116,
    text: "把世界各处已经被踩出来的做法，蒸成可流动的核心能力；再让它到谁手里，就长成谁的工具。",
    fontSize: 27,
    color: COLORS.muted,
  });
  addText(slide, {
    left: 72,
    top: 430,
    width: 760,
    height: 30,
    text: "今天不从流程讲起，直接讲终局、一个例子，以及为什么它可能会改写软件长什么样。",
    fontSize: 20,
    color: COLORS.ink,
  });

  addBox(slide, {
    left: 826,
    top: 158,
    width: 332,
    height: 346,
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
    "蒸馏的不是个人经验，也不只是团队资产，而是世界已经踩出来的做法",
    "共享的不是一个通用 app，而是可流动的核心能力",
    "前台以后应该按人显形，而不是所有人被迫共用一层壳",
  ], 854, 246, 226, 72, 20, "#FFFFFF");
}

function slide2(slide) {
  addChrome(slide, 2, 4);
  addTitle(slide, "终局：共享核心能力，前台按人显形", "不是每个人共用一个通用 app，而是把别人已经踩出来的做法，直接推成对方会用的工具。");

  addBox(slide, {
    left: 72,
    top: 188,
    width: 336,
    height: 262,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addTag(slide, "1 今天", 96, 212, 84, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 96,
    top: 258,
    width: 250,
    height: 38,
    text: "每个人都在调自己的 app",
    fontSize: 26,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "有人爱高密度，有人只要安静清单",
    "很多怪问题，别人其实已经踩过",
    "但修法、prompt、结构都烂在个人库",
  ], 96, 322, 260, 48, 16, COLORS.ink);

  addBox(slide, {
    left: 432,
    top: 188,
    width: 336,
    height: 262,
    fill: COLORS.tealSoft,
    lineFill: COLORS.tealSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "2 如果能推", 456, 212, 116, COLORS.paper, COLORS.teal);
  addBullets(slide, [
    "把 repair / prompt / flow 蒸成一个 core",
    "发给另一个人的个人库或团队库",
    "到了对方那里，不必保持原样",
  ], 456, 286, 256, 54, 17, COLORS.ink);

  addBox(slide, {
    left: 792,
    top: 188,
    width: 388,
    height: 262,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addTag(slide, "终局感", 816, 212, 84, COLORS.accentSoft, COLORS.accent);
  addBullets(slide, [
    "共享的是核心能力，不是同一套界面",
    "前台会按对方知识库、审美、权限重新长",
    "最后真正通用的，只剩同步、审查、权限、血缘",
  ], 816, 286, 286, 54, 17, COLORS.ink);

  addBox(slide, {
    left: 72,
    top: 488,
    width: 286,
    height: 114,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
    shadow: "shadow-md",
  });
  addText(slide, {
    left: 96,
    top: 512,
    width: 212,
    height: 24,
    text: "甲：偏高密度控制台",
    fontSize: 20,
    color: "#FFFFFF",
    bold: true,
  });
  addText(slide, {
    left: 96,
    top: 548,
    width: 222,
    height: 34,
    text: "把 repair、fallback、review 都堆在一屏。",
    fontSize: 16,
    color: "#E7E5E4",
  });

  addText(slide, {
    left: 374,
    top: 532,
    width: 44,
    height: 24,
    text: "→",
    fontSize: 34,
    color: COLORS.accent,
    bold: true,
    align: "center",
  });

  addBox(slide, {
    left: 432,
    top: 488,
    width: 286,
    height: 114,
    fill: COLORS.accentSoft,
    lineFill: COLORS.accentSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 456,
    top: 512,
    width: 210,
    height: 24,
    text: "中间推送的不是界面",
    fontSize: 20,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 456,
    top: 548,
    width: 220,
    height: 34,
    text: "而是蒸馏后的做法、repair 和 flow。",
    fontSize: 16,
    color: COLORS.muted,
  });

  addText(slide, {
    left: 734,
    top: 532,
    width: 44,
    height: 24,
    text: "→",
    fontSize: 34,
    color: COLORS.accent,
    bold: true,
    align: "center",
  });

  addBox(slide, {
    left: 792,
    top: 488,
    width: 388,
    height: 114,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 816,
    top: 512,
    width: 250,
    height: 24,
    text: "乙：偏极简",
    fontSize: 20,
    color: COLORS.ink,
    bold: true,
  });
  addText(slide, {
    left: 816,
    top: 548,
    width: 300,
    height: 34,
    text: "收到后，按他的知识库长成清单、面板或 agent。",
    fontSize: 16,
    color: COLORS.muted,
  });
}

function slide3(slide) {
  addChrome(slide, 3, 4);
  addTitle(slide, "doc2md 这个杂活，正好能看到它怎么长出来", "任务现场 -> 手搓修法 -> 代码年轮。蒸馏器想保住的，是后面两件事。");

  addBox(slide, {
    left: 72,
    top: 188,
    width: 318,
    height: 164,
    fill: COLORS.paper,
    lineFill: COLORS.line,
    lineWidth: 1,
    radius: "rounded-3xl",
  });
  addTag(slide, "任务现场", 96, 208, 82, COLORS.tealSoft, COLORS.teal);
  addText(slide, {
    left: 96,
    top: 248,
    width: 200,
    height: 30,
    text: "新人接手资料包",
    fontSize: 25,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "pdf、docx、xlsx 混在一起",
    "图片散在子目录里",
  ], 96, 302, 236, 30, 15, COLORS.ink);

  addBox(slide, {
    left: 72,
    top: 366,
    width: 318,
    height: 146,
    fill: COLORS.tealSoft,
    lineFill: COLORS.tealSoft,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addTag(slide, "于是手搓", 96, 388, 82, COLORS.paper, COLORS.teal);
  addBullets(slide, [
    "先扫目录，补 pdf / docx 分支",
    "路径、图片坏了就 repair，不行再 fallback",
  ], 96, 438, 236, 34, 15, COLORS.ink);
  addText(slide, {
    left: 96,
    top: 492,
    width: 224,
    height: 18,
    text: "一周后：脚本还在，但只有自己看得懂。",
    fontSize: 14,
    color: COLORS.muted,
  });

  addBox(slide, {
    left: 428,
    top: 188,
    width: 752,
    height: 72,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
    shadow: "shadow-md",
  });
  addText(slide, {
    left: 456,
    top: 208,
    width: 390,
    height: 24,
    text: "但 `doc2md` 后来没有停在脚本阶段",
    fontSize: 24,
    color: "#FFFFFF",
    bold: true,
  });
  addText(slide, {
    left: 874,
    top: 212,
    width: 262,
    height: 18,
    text: "它开始长出看得见的几圈年轮",
    fontSize: 16,
    color: "#D6D3D1",
    align: "right",
  });

  const rings = [
    [428, 278, COLORS.paper, "先长分支", "suffix 分流\npdf / docx / xlsx / pptx"],
    [816, 278, COLORS.tealSoft, "补坏样本", "扫描 PDF -> _is_scanned\n坏 docx -> _repair_docx_relationships"],
    [428, 430, COLORS.accentSoft, "挂通用兜底", "兜不住的格式\n走 generic / markitdown"],
    [816, 430, COLORS.sand, "提共享后处理", "最后收敛出\nsanitize_text / table_to_list"],
  ];

  rings.forEach((ring) => {
    addBox(slide, {
      left: ring[0],
      top: ring[1],
      width: 364,
      height: 128,
      fill: ring[2],
      lineFill: ring[2] === COLORS.paper ? COLORS.line : ring[2],
      lineWidth: ring[2] === COLORS.paper ? 1 : 0,
      radius: "rounded-3xl",
    });
    addText(slide, {
      left: ring[0] + 24,
      top: ring[1] + 24,
      width: 220,
      height: 30,
      text: ring[3],
      fontSize: 26,
      color: COLORS.ink,
      bold: true,
    });
    addText(slide, {
      left: ring[0] + 24,
      top: ring[1] + 70,
      width: 300,
      height: 40,
      text: ring[4],
      fontSize: 16,
      color: COLORS.muted,
    });
  });

  addBox(slide, {
    left: 428,
    top: 580,
    width: 752,
    height: 52,
    fill: COLORS.dark,
    lineFill: COLORS.dark,
    lineWidth: 0,
    radius: "rounded-3xl",
  });
  addText(slide, {
    left: 456,
    top: 596,
    width: 680,
    height: 18,
    text: "代码里看分支 / repair / fallback / shared，设计 md 再把这些变化记成 iteration_log。",
    fontSize: 16,
    color: "#FFFFFF",
    bold: true,
  });
}

function slide4(slide) {
  addChrome(slide, 4, 4);
  addTitle(slide, "先怎么落地", "前台先不做通用 app，先把蒸馏、推送、审查和回灌这条线跑通。");

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
    text: "推进顺序",
    fontSize: 28,
    color: COLORS.ink,
    bold: true,
  });
  addBullets(slide, [
    "先个人：先让自己少重写一类杂活",
    "再团队：promoted 开始变成团队资产",
    "再项目组：相同目的合并，不同环境保留分支",
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
