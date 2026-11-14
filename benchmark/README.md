# Benchmark

**20 câu: 15 dev, 5 test.** Câu hỏi/đáp án tiếng Việt, bằng chứng tiếng Anh.
Có 5 câu dùng filter theo mục: q05, q09, q14, q18, q20; hai câu cuối thuộc test.
23 đoạn bằng chứng, tính cả nguồn thay thế, đã được đối chiếu với text và trang.

| File | Cách dùng |
|---|---|
| `questions.md` | Đọc câu hỏi, đáp án và bằng chứng |
| `questions.jsonl` | Dữ liệu đầy đủ để chấm sau truy xuất |
| `dev_queries.jsonl`, `test_queries.jsonl` | Đầu vào tìm kiếm, chỉ chứa ID, split, câu hỏi và filter |
| `split.json` | Tập đã chốt, dấu kiểm tra và tiêu chí chọn cấu hình |
| `review_checklist.csv` | Bạn ghi `dong_y`/`can_sua` và góp ý |

Bạn mở PDF theo số trang ghi ở mỗi câu, kiểm tra bằng chứng đủ hỗ trợ đáp án,
rồi điền `student_status` và `student_note` trong checklist; lưu CSV UTF-8.
Script giữ phần đã điền khi chạy lại. Nếu sửa câu hỏi hoặc gold sau thử nghiệm,
ghi nhận phiên bản mới và chạy lại đồng nhất A/B/C. Nếu dùng kết quả test để
điều chỉnh, cần tập test mới để đánh giá độc lập.

Chạy kiểm tra bằng Python hiện có, từ gốc repo:

```powershell
python starter/scripts/validate_benchmark.py
```

Kết quả ở `../results/benchmark_validation.json`, chưa phải điểm truy xuất.
Trang bằng chứng dev/test không trùng, nhưng cùng một chương nên chủ đề còn
chồng lặp. A/B không filter; C chỉ lọc khi câu hỏi đã cung cấp phạm vi.

Chọn cấu hình theo dev: ưu tiên Evidence Hit@3, rồi Hit@1; nếu bằng nhau thì
ưu tiên thời gian ingest thấp hơn, sau đó số chunk ít hơn. Chốt cấu hình rồi
mới đọc kết quả test. Mọi sửa đổi sau khi xem test phải được ghi lại; tập test
5 câu chỉ cho kết luận trong phạm vi corpus này.
