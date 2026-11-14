# Dữ liệu

Nguồn: [A General Introduction to Artificial Intelligence](https://link.springer.com/chapter/10.1007/978-981-19-2879-6_1),
Huawei Technologies Co., Ltd., copyright 2023, online 22/10/2022.
Giấy phép [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/);
attribution và điều kiện sử dụng được ghi trong manifest.

| File | Nội dung |
|---|---|
| `raw/978-981-19-2879-6_1.pdf` | PDF gốc, giữ nguyên |
| `sources.json` | Nguồn, quyền, metadata và quy tắc chuẩn hóa |
| `page_review.json` | Trang chọn/loại và lý do |
| `manifest.json` | Kiểm kê, SHA-256, số trang và số ký tự |
| `processed/pages.jsonl` | Text của 41 trang, gồm cả trang bị loại |
| `processed/corpus.jsonl` | 40 đơn vị theo mục, từ 35 trang được chọn |
| `processed/chunks_A.jsonl`, `processed/chunks_B.jsonl` | Chunk dùng cho thí nghiệm; C dùng chung B |

Chọn trang **1-21, 23-25, 28, 30-39**. Loại **22, 26, 27, 29, 40, 41**;
lý do trong `../results/data_inventory.csv`. Đếm trang vật lý từ 1, không đếm
các đơn vị theo mục thành trang mới.

Text dùng pypdf layout và chuẩn hóa NFKC; giữ ngắt đoạn, nguồn và số trang.
Trang có nhiều mục được tách theo heading để filter đúng. Nội dung trong ảnh
và quan hệ ô/cột của bảng chưa được trích đầy đủ; từ nối qua dòng được giữ nguyên.
Ngày xác minh nguồn là 14/11/2026; ngày tải ban đầu chưa biết.

Text xử lý được Git ignore; tái tạo bằng `starter/scripts/inventory_data.py`.
Môi trường Python đã chuẩn bị; lệnh chạy bài hiện tại ở `../starter/HUONG_DAN_CHAY.md`.
Hướng dẫn rà câu hỏi và bằng chứng: `../benchmark/README.md`.
