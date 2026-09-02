import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs/teacher_class_load_20260821";
const source = JSON.parse(await fs.readFile(`${outputDir}/teacher_class_load_data.json`, "utf8"));
const workbook = Workbook.create();
const summary = workbook.worksheets.add("教师带班汇总");
const detail = workbook.worksheets.add("班级明细");

function styleHeader(range) {
  range.format.fill = "#1F4E78";
  range.format.font = { bold: true, color: "#FFFFFF" };
  range.format.horizontalAlignment = "center";
  range.format.verticalAlignment = "center";
}

summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["青少及初中团队教师带班表"]];
summary.getRange("A1").format.fill = "#163A5F";
summary.getRange("A1").format.font = { bold: true, color: "#FFFFFF", size: 16 };
summary.getRange("A1").format.horizontalAlignment = "left";
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [["统计范围：青少、初中；已排除预热、模考、定金、虚拟、校内、辅导/体验、封闭、冲刺、强化类班级。同一教师、同一明确班级系列号的续班合并计为 1 班；假期连排按学期常规上课日计入。"]];
summary.getRange("A2").format.fill = "#EAF2F8";
summary.getRange("A2").format.font = { color: "#35556F", italic: true };
summary.getRange("A2").format.wrapText = true;
const summaryHeaders = [["团队", "教师", "总班数", "周中", "周六", "周日", "合并前班号数", "排课待确认"]];
summary.getRange("A4:H4").values = summaryHeaders;
styleHeader(summary.getRange("A4:H4"));
const summaryValues = source.summary.map((row) => [row.团队, row.教师, row.总班数, row.周中, row.周六, row.周日, row.合并班号数, row.排课待确认]);
summary.getRangeByIndexes(4, 0, summaryValues.length, 8).values = summaryValues;
const summaryTable = summary.tables.add(`A4:H${summaryValues.length + 4}`, true, "TeacherLoadSummary");
summaryTable.showFilterButton = true;
summary.freezePanes.freezeRows(4);
summary.getRange(`C5:H${summaryValues.length + 4}`).format.numberFormat = "0";
summary.getRange(`A4:H${summaryValues.length + 4}`).format.borders = { preset: "insideHorizontal", style: "thin", color: "#D9E2F3" };
summary.getRange(`C5:C${summaryValues.length + 4}`).conditionalFormats.add("dataBar", { color: "#5B9BD5", gradient: true });
for (const [column, width] of [["A:A", 12], ["B:B", 22], ["C:H", 13]]) summary.getRange(column).format.columnWidth = width;
summary.getRange("A1:H1").format.rowHeight = 30;
summary.getRange("A2:H2").format.rowHeight = 38;

detail.showGridLines = false;
detail.getRange("A1:M1").merge();
detail.getRange("A1").values = [["教师带班明细（可按团队、教师与排课归类筛选）"]];
detail.getRange("A1").format.fill = "#163A5F";
detail.getRange("A1").format.font = { bold: true, color: "#FFFFFF", size: 14 };
const detailHeaders = [["团队", "教师", "班级系列号", "合并班号", "首期开课日期", "最近结课日期", "班级名称", "课程产品", "排课归类", "周中", "周六", "周日", "上课时间"]];
detail.getRange("A3:M3").values = detailHeaders;
styleHeader(detail.getRange("A3:M3"));
const detailValues = source.details.map((row) => [
  row.团队, row.教师, row.班级系列号, row.合并班号,
  new Date(`${row.首期开课日期}T00:00:00`), new Date(`${row.最近结课日期}T00:00:00`),
  row.班级名称, row.课程产品, row.排课归类, row.周中, row.周六, row.周日, row.上课时间,
]);
detail.getRangeByIndexes(3, 0, detailValues.length, 13).values = detailValues;
const detailTable = detail.tables.add(`A3:M${detailValues.length + 3}`, true, "TeacherLoadDetails");
detailTable.showFilterButton = true;
detail.freezePanes.freezeRows(3);
detail.getRange(`E4:F${detailValues.length + 3}`).format.numberFormat = "yyyy-mm-dd";
detail.getRange(`J4:L${detailValues.length + 3}`).format.numberFormat = "0";
detail.getRange(`A3:M${detailValues.length + 3}`).format.borders = { preset: "insideHorizontal", style: "thin", color: "#E5E7EB" };
for (const [column, width] of [["A:A", 11], ["B:B", 22], ["C:C", 13], ["D:D", 28], ["E:F", 13], ["G:G", 38], ["H:H", 28], ["I:I", 14], ["J:L", 10], ["M:M", 70]]) detail.getRange(column).format.columnWidth = width;
detail.getRange(`D4:M${detailValues.length + 3}`).format.wrapText = true;

await fs.mkdir(outputDir, { recursive: true });
const file = await SpreadsheetFile.exportXlsx(workbook);
await file.save(`${outputDir}/教师带班表_20260821.xlsx`);
const check = await workbook.inspect({ kind: "table", range: "教师带班汇总!A1:H20", include: "values", tableMaxRows: 20, tableMaxCols: 8 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, summary: "formula errors" });
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "教师带班汇总", range: "A1:H30", scale: 1.5 });
await fs.writeFile(`${outputDir}/教师带班汇总_preview.png`, new Uint8Array(await preview.arrayBuffer()));
const detailPreview = await workbook.render({ sheetName: "班级明细", range: "A1:M20", scale: 1.2 });
await fs.writeFile(`${outputDir}/班级明细_preview.png`, new Uint8Array(await detailPreview.arrayBuffer()));
