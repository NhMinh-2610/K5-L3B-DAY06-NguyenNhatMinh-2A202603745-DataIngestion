# Chạy lab

Mở Docker Desktop. Chạy từ gốc repo bằng Python 3.13 đã chuẩn bị:

```powershell
$labPython = "$env:USERPROFILE\.venvs\day06-dataingestion\Scripts\python.exe"
docker compose -p day6_student_starter -f starter/docker-compose.yml up -d --wait --pull never
& $labPython starter/scripts/check_setup.py
& $labPython starter/scripts/inventory_data.py
& $labPython starter/scripts/validate_benchmark.py
& $labPython starter/scripts/prepare_chunks.py
& $labPython starter/scripts/ingest_vectors.py
& $labPython -X utf8 -m starter.src.run --split dev
```

Môi trường đặt ngoài OneDrive để tránh lỗi đường dẫn dài; tái sử dụng thư viện
sẵn có. Phiên bản: `../results/setup.json`, `../results/ingestion.json`.
Database `day6_lab` ở `127.0.0.1:15433`; `.env` được tạo từ mẫu và Git ignore.

Model `intfloat/multilingual-e5-small` chạy local, không cần API key, 384 chiều.
Phiên bản cố định trong `embedding.json`. Theo [hướng dẫn model](https://huggingface.co/intfloat/multilingual-e5-small),
tài liệu thêm `passage: `, câu hỏi thêm `query: `; vector được chuẩn hóa.
Tìm kiếm cosine exact bằng pgvector, filter metadata thực hiện trước top-3.

Cấu hình A/B/C: `strategies.json`. C dùng lại embedding B; thời gian ingest C
chỉ gồm phần lưu, không gồm tạo embedding. Cache vector kiểm tra theo model và
hash chunk. Mỗi lần upsert nhận toàn bộ snapshot của cấu hình, bỏ chunk cũ trong
cùng transaction; từ chối dữ liệu rỗng hoặc model khác.

Kết quả: `../results/chunk_stats.csv`, `../results/ingestion.json`.
Checklist bài nộp: `../SUBMISSION.md`; hướng dẫn rà nhãn: `../results/CHAM_DIEM.md`.

Lệnh dev chạy 15 câu cho cả A/B/C, sau đó đối chiếu gold. Xem
`../results/dev_metrics.csv` để đọc chỉ số và `../results/dev_trace.jsonl` để
kiểm tra từng top-3. `../results/selection.json` ghi cấu hình C đã chốt trước test.
Test đã chạy trên cùng cấu hình/model. Chạy lại bằng:

```powershell
& $labPython -X utf8 -m starter.src.run --split test
& $labPython -X utf8 starter/scripts/prepare_audit.py
```

Kết quả ở `../results/test_metrics.csv`, `../results/test_trace.jsonl`.
Ba bảng đã có điểm nháp và lý do. Rà theo `../results/CHAM_DIEM.md`,
sửa điểm nếu cần và đặt `review_status=confirmed` cho từng dòng đã kiểm tra.
Xem tổng hợp nháp bằng `prepare_audit.py --summarize --draft`.
Sau khi xác nhận đủ:

```powershell
& $labPython -X utf8 starter/scripts/prepare_audit.py --summarize
```
Các hit tự động yêu cầu đúng nguồn/trang và chứa đủ đoạn bằng chứng đã chốt;
bằng chứng tương đương cần được đối chiếu riêng. Tập test chỉ chạy sau khi chốt cấu hình.

Kiểm tra toàn bộ dữ liệu, trace, chỉ số và các dòng database mà không chạy lại test:

```powershell
& $labPython -X utf8 starter/scripts/check_lab.py --database
```

Kết quả ở `../results/lab_check.json`. Cổng lab đã đổi từ 55433 sang 15433
vì dải cổng cũ đang được Windows dành riêng; giữ nguyên Docker volume và cấu hình truy xuất.

Các lệnh dựng lại môi trường trên máy khác:

```powershell
python -m venv --system-site-packages "$env:USERPROFILE\.venvs\day06-dataingestion"
& $labPython -m pip install -r starter/requirements.txt
docker pull pgvector/pgvector:0.8.7-pg16
& $labPython -c "from huggingface_hub import snapshot_download; snapshot_download('intfloat/multilingual-e5-small', revision='614241f622f53c4eeff9890bdc4f31cfecc418b3', allow_patterns=['*.json','*.safetensors','*.model'])"
```

Dừng riêng database lab và giữ dữ liệu:

```powershell
docker compose -p day6_student_starter -f starter/docker-compose.yml stop
```
