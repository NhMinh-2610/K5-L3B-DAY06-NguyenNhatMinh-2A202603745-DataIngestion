# Rà và xác nhận điểm nháp

Ba bảng đã có điểm do mô hình ngôn ngữ đề xuất kèm lý do, dựa trên text trích xuất,
vị trí nguồn và top-3. Tất cả đang có `review_status=draft`; đây chưa phải nhãn đã được
người học xác nhận. Mở PDF để kiểm tra từng dòng, sửa điểm/lý do khi cần,
rồi đổi `review_status` của dòng đã rà thành `confirmed`. Lưu CSV UTF-8.

Mở ba file CSV bằng ứng dụng bảng tính đang có. Chỉ điền các cột chấm dưới đây;
giữ nguyên ID, nội dung, thứ hạng và số trang. Lưu CSV UTF-8.

| File | Cột bạn điền | Cách chấm |
|---|---|---|
| `manual_coherence.csv` — 30 dòng | `score`, `reason` | 0: cắt giữa ý/thiếu chủ thể làm không hiểu; 1: hiểu một phần, thiếu ngữ cảnh; 2: tự hiểu được và giữ trọn ý. Ghi lý do. |
| `manual_grounding.csv` — 15 dòng | `score`, `reason` | Đọc câu hỏi, đáp án và toàn bộ top-3. 0: không có bằng chứng; 1: có nhưng thiếu điều kiện/ngữ cảnh; 2: đủ để trả lời và truy nguồn. Ghi lý do. |
| `manual_metadata.csv` — 45 dòng | `source_ok`, `page_ok`, `section_ok`, `reason` | Mở PDF theo trang của chunk, kiểm tra nguồn/trang/mục. Điền 1 nếu đủ và đúng, 0 nếu thiếu/sai. Nếu có 0, ghi lỗi ở reason. |

Coherence dùng cùng 10 vị trí trên 10 trang nội dung đầu, đã chọn trước khi chạy
test. B/C có cùng chunk nên có thể dùng lại cùng điểm và lý do khi `chunk_id` giống nhau.

## Xác nhận bằng chứng truy xuất trong bảng grounding

- `auto_hit1`, `auto_hit3` là kết quả so khớp toàn bộ quote; giữ nguyên.
- Điền `verified_hit1`: 1 nếu chunk hạng 1 có đủ bằng chứng ở nguồn/trang hợp lệ,
  ngược lại 0.
- Điền `verified_hit3`: 1 nếu ít nhất một chunk trong top-3 tự chứa đủ bằng chứng,
  ngược lại 0. Không ghép nhiều chunk để tính chỉ số này.
- Chấp nhận đoạn tương đương dù không trùng toàn bộ câu gold; ghi đoạn/trang và
  lý do ở `reason`. Nếu công nhận Hit@1 thì Hit@3 cũng phải là 1.
- Grounding được xem chung top-3, nên có thể đủ thông tin dù Hit@3 chưa đạt.
- Ví dụ q20: kiểm tra đoạn trang 38 có đủ điều kiện riêng tư/an toàn dữ liệu không;
  phần tham chiếu hình bị thiếu không tự động có nghĩa là thiếu nội dung trả lời.

Metadata đúng không đồng nghĩa truy xuất đúng đáp án: chunk ở trang khác gold
vẫn có `page_ok=1` nếu metadata ghi đúng trang thật chứa chunk đó.

## Tổng hợp sau khi chấm xong

Từ gốc repo, chạy:

```powershell
$labPython = "$env:USERPROFILE\.venvs\day06-dataingestion\Scripts\python.exe"
& $labPython -X utf8 starter/scripts/prepare_audit.py --summarize
```

Kết quả: `manual_metrics.csv`. Lệnh sẽ báo vị trí thiếu điểm/lý do, không tự điền
0 cho ô trống và từ chối nhãn chưa xác nhận. Bảng kết quả tự động ban đầu
vẫn được giữ ở `test_metrics.csv`. Cấu hình C giữ nguyên sau test.

Để xem tổng hợp nháp trước khi xác nhận, chạy cùng lệnh với thêm `--draft`.
Kết quả ở `draft_manual_metrics.csv`; không dùng file này làm điểm thủ công cuối.
