# Báo cáo cá nhân — Day 6

**Nguyễn Nhật Minh — 2A202603745 — H201**

Ngày tổng hợp: 14/11/2026. Các chỉ số truy xuất đã chạy; điểm chấm bổ sung hiện là **nháp, chưa được học viên xác nhận**.

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** Chương *A General Introduction to Artificial Intelligence*, Huawei Technologies Co., Ltd. (2023), trong *Artificial Intelligence Technology*, [DOI 10.1007/978-981-19-2879-6_1](https://link.springer.com/chapter/10.1007/978-981-19-2879-6_1), giấy phép CC BY-NC-ND 4.0. PDF có 41 trang vật lý; chọn **35 trang nội dung**: 1–21, 23–25, 28, 30–39. Loại các trang chủ yếu là hình, trang hỗn hợp tóm tắt/bài tập và trang giấy phép. Đếm mỗi trang vật lý một lần; 40 đơn vị theo mục không làm tăng số trang. Nguồn và quy tắc kiểm kê: `data/manifest.json`, `data/page_review.json`.
- **Chuẩn hóa, lỗi và giới hạn:** pypdf 6.21.4 trích text ở chế độ layout; chuẩn hóa Unicode NFKC, khoảng trắng và header/footer đã xác định, giữ ngắt đoạn và vị trí nguồn. Văn bản hình/bảng chưa được trích đầy đủ; dấu nối cuối dòng được giữ lại. Lần kiểm kê lưu gần nhất không có lỗi trích xuất; trang 22 rỗng sau bỏ header, có một cảnh báo PDF. Chi tiết: `results/data_quality.md`, `results/data_preparation.log`.
- **Embedding model/provider/version/số chiều, vector store/version, metric và chi phí:** `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, Sentence Transformers 6.2.0 chạy local trên CPU, vector 384 chiều và chuẩn hóa L2. Document thêm `passage: `, query thêm `query: `. PostgreSQL 16.16 + pgvector 0.8.7, lưu bền vững trong Docker volume; tìm **cosine exact** và lọc metadata trước top-3. Phí dịch vụ ghi nhận **0 USD**, chưa tính điện và phần cứng. Nạp lặp giữ nguyên số dòng; snapshot mới cập nhật chunk và loại chunk cũ. Phiên bản và kiểm tra: `starter/embedding.json`, `results/setup.json`, `results/ingestion.json`.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:** `document_id` là mã tài liệu; `source` là URL nguồn; `page` là số trang PDF vật lý. `section` và `section_title` lấy từ heading trong tài liệu, dùng lọc phạm vi; `language=en`, `year=2023`, `document_type=book_chapter` lấy từ metadata nguồn. `page` và `year` là số nguyên, các trường nêu trên còn lại là chuỗi. Các vị trí ký tự trong trang giúp đối chiếu chunk với text gốc.

Lệnh chạy từ PowerShell tại gốc repo, sau khi mở Docker Desktop; đợi từng lệnh hoàn tất rồi kiểm tra kết quả:

```powershell
$labPython = "$env:USERPROFILE\.venvs\day06-dataingestion\Scripts\python.exe"
docker compose -p day6_student_starter -f starter/docker-compose.yml up -d --wait --pull never
& $labPython -X utf8 starter/scripts/inventory_data.py
& $labPython -X utf8 starter/scripts/validate_benchmark.py
& $labPython -X utf8 starter/scripts/prepare_chunks.py
& $labPython -X utf8 starter/scripts/ingest_vectors.py
& $labPython -X utf8 -m starter.src.run --split dev
& $labPython -X utf8 -m starter.src.run --split test
```

Test chỉ chạy sau khi cấu hình C đã chốt. [Hướng dẫn chạy bài hiện tại](../../starter/HUONG_DAN_CHAY.md); database dùng `127.0.0.1:15433`. [Hướng dẫn starter gốc](../../starter/README.md) được giữ nguyên theo đề bài.

## Cấu hình và benchmark

- **A / B / C:** A chia cố định tối đa 500 ký tự, overlap 50, không filter: 190 chunk. B chia theo đoạn tối đa 500 ký tự, overlap 0, không filter: 201 chunk. C dùng lại chunk và vector của B, lọc `section` trước khi xếp hạng nếu câu hỏi yêu cầu: 201 chunk. B–C chỉ khác việc áp dụng filter; A–B thay cả ranh giới chia và overlap. Khi câu hỏi không có filter, C tìm như B. Cùng corpus, model, vector store và câu hỏi cho cả ba cấu hình.
- **20 câu và evidence:** Bộ câu hỏi tiếng Việt gồm 15 dev `q01–q15` và 5 test `q16–q20`, tách trước thử nghiệm. Câu có filter: `q05`, `q09`, `q14` ở dev; `q18`, `q20` ở test. Mỗi câu có đáp án, nguồn/trang, quote và trang thay thế nếu có. Đối chiếu quote, vị trí và mục với corpus bằng `starter/scripts/validate_benchmark.py`; checklist 20 câu trong `benchmark/review_checklist.csv` vẫn chờ học viên rà PDF. Query chỉ chứa ID, split, câu hỏi và filter; gold dùng sau truy xuất.
- **Tiêu chí chọn trước test:** Ưu tiên Evidence Hit@3 trên dev, sau đó Hit@1; nếu vẫn bằng nhau xét thời gian ingest rồi số chunk. C đạt 10/15 Evidence Hit@3 trên dev, cao hơn A/B 9/15, nên được chốt trước test trong `results/selection.json`.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | Dev | 5/15 | 9/15 | 190 | 11,6721 giây* | 0 USD |
| B | Dev | 7/15 | 9/15 | 201 | 10,8491 giây* | 0 USD |
| C | Dev | 8/15 | 10/15 | 201 | 0,2849 giây* | 0 USD |
| A | Test | 0/5 | 1/5 | 190 | 11,6721 giây* | 0 USD |
| B | Test | 0/5 | 1/5 | 201 | 10,8491 giây* | 0 USD |
| C | Test | 0/5 | 1/5 | 201 | 0,2849 giây* | 0 USD |

*Thời gian là ingest lần đầu đã ghi, dùng chung cho hai split; chưa gồm 35,0504 giây tải model. C dùng lại vector B nên thời gian C chỉ phản ánh phần tái sử dụng và lưu, chưa gồm tạo vector từ đầu. A dùng 87.463 ký tự/20.381 token, B và C dùng 79.767 ký tự/18.601 token; token gồm tiền tố. Nguồn số liệu: `results/chunk_stats.csv`, `results/ingestion.json`.

Hit@1 xét chunk hạng đầu; Evidence Hit@3 xét ít nhất một chunk trong top-3 tự chứa đủ bằng chứng ở nguồn/trang hợp lệ. Bảng trên là đối chiếu tự động theo **toàn bộ quote đã lưu** sau chuẩn hóa Unicode/khoảng trắng. Đoạn tương đương cần được học viên rà riêng; số tự động không bị thay đổi.

**Bảng dưới là điểm nháp để rà, chưa phải kết quả chấm thủ công đã xác nhận.** Filter là tỷ lệ trên hai câu test có yêu cầu; A/B không áp dụng filter nên kết quả đúng phạm vi có thể xuất hiện tình cờ.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,0 (10), nháp | 15/15, nháp | 0/2 | 3/0/2; 0,8, nháp |
| B | 1,0 (10), nháp | 15/15, nháp | 1/2 | 3/0/2; 0,8, nháp |
| C | 1,0 (10), nháp | 15/15, nháp | 2/2 | 3/0/2; 0,8, nháp |

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:** `results/dev_trace.jsonl`, `results/test_trace.jsonl`; các bảng `results/manual_coherence.csv`, `results/manual_metadata.csv`, `results/manual_grounding.csv`; tổng hợp nháp `results/draft_manual_metrics.csv`. Coherence dùng cùng 10 vị trí giữa text trên 10 trang nội dung đầu, được chọn trước test; metadata kiểm tra 5 câu test × top-3 cho từng cấu hình; grounding chấm top-3 của 5 câu test cho từng cấu hình. `results/audit_sampling.json` ghi quy tắc chọn mẫu.

Nhãn nháp được mô hình ngôn ngữ đề xuất từ text trích xuất, top-3, đáp án và vị trí nguồn; 90 dòng đều còn `review_status=draft`. Học viên cần đối chiếu PDF, sửa điểm/lý do và xác nhận từng dòng theo `results/CHAM_DIEM.md`. Grounding xét độ đủ bằng chứng trong top-3; việc ghép nhiều chunk không thay định nghĩa Evidence Hit@3 một chunk.

## Phân tích và kết luận

- **So sánh A–B và B–C; hai ví dụ sai:** Trên dev, B tăng Hit@1 từ 5/15 lên 7/15 so với A, còn Evidence Hit@3 cùng 9/15; A/B khác cả cách chia và overlap. C tăng Evidence Hit@3 dev từ 9/15 lên 10/15 so với B. Trên test, B và C đều 1/5 theo quote đầy đủ; C tuân thủ filter 2/2, B đạt 1/2. Với C, `q16` trả hạng 1 là tiêu đề ở **trang PDF 12**, chưa nêu ba trường phái; `q18` trả các đoạn **trang 33–34** đúng mục 1.4 nhưng thiếu khác biệt giữa online và batch inference. Cả hai ví dụ thuộc nguồn sách nêu ở phần dữ liệu; chi tiết trong `results/test_trace.jsonl`.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** Giữ C đã chốt theo dev. Filter giúp giới hạn theo mục khi phạm vi được cung cấp và metadata đáng tin, nhưng không bảo đảm đoạn đứng đầu chứa đủ ý. Chia theo đoạn vẫn có thể tạo chunk chỉ có tiêu đề hoặc bị cắt; C dùng lại vector B nên tiết kiệm lần encode bổ sung.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, thời gian/chi phí:** Chỉ có một chương sách, năm câu test, câu hỏi tiếng Việt trên tài liệu tiếng Anh; chủ đề dev/test có thể gần nhau. Hình/bảng và ranh giới chunk làm mất ngữ cảnh. So khớp toàn bộ quote có thể bỏ sót đoạn tương đương: ví dụ `q20` C, hạng 1 trang 38 có điều kiện riêng tư và an toàn dữ liệu nhưng thiếu cuối quote; việc công nhận cần học viên xác nhận. Nhãn trong bảng thứ hai là đề xuất chưa xác nhận, có thể thiên lệch. Thời gian đo một lần và có cache; phí 0 USD chưa gồm điện/phần cứng.
- **Nếu làm lại hoặc mở rộng:** Rà bằng chứng với PDF, gắn tiêu đề với đoạn giải thích và thử kích thước/overlap trên dev. Vì đã xem test, nếu dùng các lỗi test để sửa pipeline thì cần tập test mới để đánh giá độc lập.

Để hoàn thiện bài, học viên rà 20 câu trong `benchmark/review_checklist.csv`, rồi rà ba bảng theo `results/CHAM_DIEM.md`, đổi `review_status` thành `confirmed` sau khi kiểm tra từng dòng. Sau đó chạy:

```powershell
& $labPython -X utf8 starter/scripts/prepare_audit.py --summarize
```

Đọc `results/manual_metrics.csv` và cập nhật bảng chấm thủ công trong báo cáo bằng kết quả đã xác nhận.
