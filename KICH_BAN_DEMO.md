# Kịch bản demo lab — khoảng 5 phút

Đọc phần trong dấu ngoặc kép; các dòng **Thao tác** là việc bạn làm trên màn hình.

## Chuẩn bị trước khi lên

- Mở Docker Desktop và đợi ứng dụng chạy xong.
- Mở thư mục repo trong File Explorer, gõ `powershell` vào thanh địa chỉ rồi nhấn Enter. Chạy các lệnh dưới đây tại cửa sổ đó.
- Mở sẵn file này và các file được nhắc đến bên dưới trong trình soạn thảo đang dùng.

## 1. Giới thiệu dữ liệu — 45 giây

**Thao tác:** Mở `data/raw/978-981-19-2879-6_1.pdf`, sau đó mở `data/manifest.json`.

> “Em xin trình bày pipeline xử lý tài liệu và tìm kiếm bằng chứng cho câu hỏi. Dữ liệu là chương *A General Introduction to Artificial Intelligence*. PDF có 41 trang, trong đó em sử dụng 35 trang nội dung sau khi kiểm kê.
>
> File có lớp văn bản nên trích xuất trực tiếp được. Manifest lưu thông tin nguồn, mã kiểm tra file và danh sách trang. Khi chia nhỏ văn bản, mỗi đoạn vẫn giữ nguồn, trang và mục để truy ngược về PDF.”

## 2. Giải thích ba cấu hình — 45 giây

**Thao tác:** Mở `starter/strategies.json`.

> “Em so sánh ba cấu hình. A chia đoạn tối đa 500 ký tự, chồng lấn 50 ký tự. B chia theo đoạn văn, tối đa 500 ký tự và không chồng lấn. C dùng lại các đoạn của B, đồng thời lọc theo metadata khi câu hỏi có yêu cầu.
>
> A có 190 đoạn; B và C có 201 đoạn mỗi cấu hình. Cả ba dùng cùng model đa ngữ multilingual-e5-small, tạo vector 384 chiều và lưu trong PostgreSQL với pgvector. Hệ thống tìm ba đoạn gần nhất theo cosine; với C, điều kiện lọc được áp dụng trước khi lấy top-3.”

## 3. Chạy demo — khoảng 1 phút

**Thao tác:** Chạy lần lượt trong PowerShell:

```powershell
$labPython = "$env:USERPROFILE\.venvs\day06-dataingestion\Scripts\python.exe"
docker compose -p day6_student_starter -f starter/docker-compose.yml up -d --wait --pull never
& $labPython -X utf8 -m starter.src.run --split test
```

> “Dữ liệu và vector đã được lưu từ bước ingest. Bây giờ em chạy lại năm câu test cho cả ba cấu hình trên dữ liệu đó. Đầu vào tìm kiếm chỉ có câu hỏi và điều kiện lọc. Sau khi lấy kết quả, chương trình mới đối chiếu với bằng chứng chuẩn.”

Đợi chạy xong rồi kiểm tra kết quả ở bước tiếp theo. Nếu có lỗi, giữ thông báo lỗi để kiểm tra; có thể mở kết quả đã lưu và nói rõ đó là lần chạy trước.

## 4. Chỉ ra một câu đạt và một câu lỗi — 1 phút

**Thao tác:** Chạy lệnh này để hiển thị hai câu của cấu hình C:

```powershell
Get-Content -LiteralPath results/test_trace.jsonl | ForEach-Object {
    $demoRow = $_ | ConvertFrom-Json
    if ($demoRow.strategy -eq 'C' -and $demoRow.id -in @('q16', 'q19')) {
        $demoRow | Select-Object id, question, hit_at_1, evidence_hit_at_3 | Format-List
        $demoRow.hits | Select-Object rank, page, text, evidence_hit | Format-List
    }
}
```

> “Với q16, câu hỏi yêu cầu tên ba trường phái AI. Đoạn đầu tiên ở trang 12 chỉ có tiêu đề, chưa có tên ba trường phái; hai đoạn còn lại cũng không đủ bằng chứng. Vì vậy câu này không đạt.
>
> Với q19, câu hỏi hỏi cách hai nhóm mạng trong GAN tương tác. Đoạn hạng hai ở trang 37 mô tả hai nhóm cạnh tranh với nhau, kèm ví dụ người làm tiền giả và người kiểm tra. Vì bằng chứng ở hạng hai nên câu này đạt Evidence Hit@3 nhưng không đạt Hit@1.”

## 5. Trình bày kết quả và hạn chế — 1 phút

**Thao tác:** Mở `results/dev_metrics.csv`, `results/selection.json`, rồi `results/test_metrics.csv`.

> “Benchmark có 20 câu, chia trước thành 15 câu dev và 5 câu test. Trên dev, Evidence Hit@3 của A và B đều là 9/15, còn C là 10/15. Vì vậy em chốt C trước khi chạy test.
>
> Trên test, cả ba cấu hình có Hit@1 là 0/5 và Evidence Hit@3 là 1/5 theo cách đối chiếu tự động yêu cầu chứa toàn bộ đoạn bằng chứng chuẩn. C tuân thủ điều kiện lọc ở cả hai câu test có yêu cầu, nhưng lọc đúng mục vẫn chưa bảo đảm lấy đủ bằng chứng.
>
> Qua ví dụ q16, một hạn chế là đoạn tiêu đề quá ngắn vẫn có thể được xếp hạng cao. Chia đoạn cũng có thể cắt mất ngữ cảnh. Hướng cải thiện tiếp theo là gắn tiêu đề với đoạn giải thích và kiểm tra đoạn thiếu ý trên dev; không đổi cấu hình dựa trên năm câu test đã xem.”

Nếu được hỏi phần chấm thủ công khi bạn chưa điền xong, nói đúng tiến độ:

> “Ba bảng coherence, grounding và metadata đã được chuẩn bị. Đã có điểm nháp kèm lý do; phần rà nguồn và xác nhận thủ công chưa hoàn tất nên em chưa có kết luận cuối cùng từ các bảng này.”

## Việc bạn cần làm

1. Chạy thử mục 3, rồi kiểm tra mục 4 trước buổi demo để quen thao tác.
2. Tự chấm ba bảng theo `results/CHAM_DIEM.md` và hoàn thiện báo cáo. Khi chấm xong, thay câu nói về tiến độ ở trên bằng kết quả thực tế của bạn.

File này đã soạn sẵn lời trình bày và lệnh chạy; các ô chấm thủ công vẫn do bạn điền.
