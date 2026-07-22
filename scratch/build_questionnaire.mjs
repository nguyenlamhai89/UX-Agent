import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/madebynham/Desktop/UX Agent/outputs/questionnaire-table";
const outputPath = `${outputDir}/questionnaire-table.xlsx`;

const rows = [
  [1, "0. Warm-up", "Để tiện xưng hô, anh chị có thể giới thiệu về bản thân được không", "Họ và tên\nTuổi\nCông việc hiện tại"],
  [2, "0. Warm-up", "Với công việc hiện tại thì một ngày của anh chị thường diễn ra như thế nào? Có bận rộn không?", "Một ngày diễn ra"],
  [3, "0. Warm-up", "Anh chị đang có những người thân nào mới sang học tập/làm việc ở nước ngoài?", "Mối quan hệ với người thân\nQuốc gia của người thân"],
  [4, "0. Warm-up", "Khi họ mới sang, anh chị thường nghe họ kể về những khó khăn nào?", "Khó khăn khi mới tới nước ngoài của người thân"],
  [5, "0. Warm-up", "Hiện tại anh chị đang sử dụng ứng dụng ngân hàng nào trong cuộc sống thường nhật?", "Ứng dụng ngân hàng đang sử dụng"],
  [6, "0. Warm-up", "Anh chị sử dụng (những) ứng dụng ngân hàng đó cho (những) mục đích gì?", "Mục đích sử dụng ngân hàng tương ứng"],
  [7, "0. Warm-up", "Vì sao anh chị lại chọn (những) ngân hàng đó để phục vụ cho (những) mục đích đó mà không phải là ngân hàng khác?", "Tiêu chí lựa chọn ngân hàng cho mục đích sử dụng tương ứng"],
  [8, "1. Awareness", "Anh chị thường chuyển tiền cho họ vào những dịp nào với tần suất/năm như thế nào? (học phí, viện phí...)", "Mục đích CTQT\nTần suất CTQT"],
  [9, "1. Awareness", "Anh chị đã nhận được thông báo về khoản chi phí cần đóng như thế nào?", "Nhận thức cần CTQT"],
  [10, "1. Awareness", "Khi anh chị nhận được thông báo về khoản chi phí cần đóng thì suy nghĩ/cảm giác đầu tiên xuất hiện trong đầu anh chị lúc đó là gì?", "Cảm xúc khi nhận thông báo cần CTQT"],
  [11, "2. Consideration", "Ở thời điểm cần chuyển tiền cho họ, anh chị biết những cách nào để chuyển được tiền cho họ?", "Các cách CTQT đã biết"],
  [12, "2. Consideration", "Anh chị biết đến những cách đó từ đâu?", "Nguồn thông tin các phương thức CTQT"],
  [13, "2. Consideration", "Khi đứng trước nhiều lựa chọn chuyển tiền như vậy thì anh chị cảm thấy như thế nào? Anh chị cảm thấy rõ ràng, hoang mang hay là một cảm giác nào khác?", "Cảm xúc khi cân nhắc các phương thức CTQT"],
  [14, "3. Decision Making", "Anh chị đã/đang lựa chọn chuyển bằng những cách nào?", "Các phương thức CTQT đã/đang chọn"],
  [15, "3. Decision Making", "Tiêu chí lựa chọn của Anh chị là gì? Vì sao bạn chọn cách đó mà không phải các cách khác?", "Tiêu chí lựa chọn phương thức CTQT"],
  [16, "3. Decision Making", "Anh chị cảm thấy như thế nào về quyết định lựa chọn cách chuyển tiền đó? Anh chị cảm thấy yên tâm, lo lắng hay là một cảm giác nào khác?", "Cảm xúc khi lựa chọn phương thức CTQT hiện tại"],
  [17, "4. Usage", "Hãy kể về lần gần nhất Anh chị chuyển tiền cho người khác ở nước ngoài. Anh chị đã trải qua các bước như thế nào từ khi có nhu cầu (gồm những gì, mất bao lâu)", "Quá trình chuẩn bị giấy tờ CTQT\nQuá trình Chuyển tiền"],
  [18, "4. Usage", "Vì sao Anh chị lại quyết định làm điều A/B/C đó trong quá trình trên? (optional)", "Động lực của các hành vi trong quá trình Chuyển tiền"],
  [19, "4. Usage", "Trên thang điểm 10, Anh chị đánh giá mức độ hài lòng về quá trình chuyển tiền trên bao nhiêu điểm?", "Đánh giá quá trình Chuyển tiền"],
  [20, "4. Usage", "Vì sao Anh chị đưa ra số điểm như vậy? (điểm cộng, điểm trừ là gì) (về thông tin hiển thị, số bước, giấy tờ cần chuẩn bị, các phương thức chuyển tiền,...)", "Khó khăn khi Chuyển tiền"],
  [21, "4. Usage", "Anh chị đã/đang giải quyết khó khăn đó như thế nào?", "Cách giải quyết khó khăn khi Chuyển tiền"],
  [22, "4. Usage", "Lần đó mất bao lâu để người kia nhận được tiền từ bạn? Anh chị đã theo dõi quá trình tiền gửi cho người đó như thế nào?", "Quá trình Chờ người kia nhận tiền"],
  [23, "4. Usage", "Vì sao Anh chị lại quyết định làm điều A/B/C đó trong quá trình trên? (optional)", "Động lực của các hành vi trong quá trình Chờ người kia nhận tiền"],
  [24, "4. Usage", "Trên thang điểm 10, Anh chị đánh giá mức độ hài lòng về quá trình theo dõi trên bao nhiêu điểm?", "Đánh giá quá trình Chờ người kia nhận tiền"],
  [25, "4. Usage", "Vì sao Anh chị đưa ra số điểm như vậy? (điểm cộng, điểm trừ là gì) (về thông tin hiển thị, thời gian,...)", "Khó khăn khi Chờ người kia nhận tiền"],
  [26, "4. Usage", "Anh chị đã/đang giải quyết khó khăn đó như thế nào?", "Cách giải quyết khó khăn khi Chờ người kia nhận tiền"],
  [27, "5. Advocacy", "Anh chị có sẵn sàng chia sẻ giải pháp chuyển tiền quốc tế đang sử dụng cho những người có nhu cầu giống anh chị không? Anh chị đánh giá mức độ sẵn sàng của bản thân bao nhiêu điểm trên 10?", "Mức độ sẵn sàng chia sẻ giải pháp hiện tại"],
  [28, "5. Advocacy", "Vì sao Anh chị đưa ra số điểm như vậy? (điểm cộng, điểm trừ là gì)", "Rào cản để chia sẻ giải pháp hiện tại"],
];

const colors = {
  "0. Warm-up": "#E5E7EB",
  "1. Awareness": "#D9F0C2",
  "2. Consideration": "#CFE8F8",
  "3. Decision Making": "#FFE7A8",
  "4. Usage": "#FFD2B8",
  "5. Advocacy": "#E5D1F4",
};

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Questionnaire");
sheet.showGridLines = false;
sheet.getRange("A1:D1").merge();
sheet.getRange("A1").values = [["Bảng câu hỏi phỏng vấn — Chuyển tiền quốc tế"]];
sheet.getRange("A2:D2").merge();
sheet.getRange("A2").values = [["Nguồn: CleanShot 2026-07-22 at 11.10.10.png"]];
sheet.getRange("A4:D4").values = [["STT", "Giai đoạn", "Câu hỏi", "Mục tiêu / Chủ đề khai thác"]];
sheet.getRange(`A5:D${rows.length + 4}`).values = rows;

sheet.getRange("A1:D1").format = { fill: "#17365D", font: { bold: true, color: "#FFFFFF", size: 16 }, horizontalAlignment: "left", verticalAlignment: "center" };
sheet.getRange("A2:D2").format = { font: { italic: true, color: "#666666", size: 10 }, horizontalAlignment: "left", verticalAlignment: "center" };
sheet.getRange("A4:D4").format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
sheet.getRange(`A4:D${rows.length + 4}`).format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
sheet.getRange(`A5:A${rows.length + 4}`).format = { horizontalAlignment: "center", verticalAlignment: "top" };
sheet.getRange(`B5:D${rows.length + 4}`).format = { verticalAlignment: "top", wrapText: true };

for (let index = 0; index < rows.length; index += 1) {
  const row = index + 5;
  sheet.getRange(`B${row}`).format.fill = colors[rows[index][1]];
}

sheet.getRange("A:A").format.columnWidth = 8;
sheet.getRange("B:B").format.columnWidth = 23;
sheet.getRange("C:C").format.columnWidth = 62;
sheet.getRange("D:D").format.columnWidth = 44;
sheet.getRange("A1:D1").format.rowHeight = 30;
sheet.getRange("A2:D2").format.rowHeight = 20;
sheet.getRange("A4:D4").format.rowHeight = 28;
sheet.getRange(`A5:D${rows.length + 4}`).format.rowHeight = 46;
sheet.freezePanes.freezeRows(4);
sheet.getRange(`B5:B${rows.length + 4}`).dataValidation = { rule: { type: "list", values: Object.keys(colors) } };

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const preview = await workbook.render({ sheetName: "Questionnaire", range: "A1:D32", scale: 1.5, format: "png" });
await fs.writeFile(`${outputDir}/questionnaire-preview.png`, new Uint8Array(await preview.arrayBuffer()));

const inspection = await workbook.inspect({ kind: "table", range: "Questionnaire!A1:D32", include: "values", tableMaxRows: 32, tableMaxCols: 4 });
console.log(inspection.ndjson);
console.log(`OUTPUT=${outputPath}`);
