# Kiểm kê dữ liệu

- Chọn **35/41 trang**, đạt tối thiểu 30 trang nội dung.
- Loại trang: 22, 26, 27, 29, 40, 41; lý do trong `data_inventory.csv`.
- Số ký tự: 79,973; số đơn vị theo mục: 40.
- Trích bằng pypdf 6.21.4, chế độ layout, chuẩn hóa nfkc-layout-whitespace-v1.
- Đếm trang vật lý từ 1; đơn vị theo mục không được tính thêm thành trang.
- Lỗi trích xuất: []; trang rỗng sau bỏ header: [22].
- Cảnh báo PDF: 1, gồm 0 cảnh báo thiếu fontTools tùy chọn; chi tiết ở `data_preparation.log`.

Các trang có nhiều mục được tách thành các khoảng ký tự để giữ đúng filter.
Text trong hình và quan hệ ô/cột của bảng chưa được trích đầy đủ. Dấu nối cuối
dòng được giữ nguyên; cần đối chiếu nguồn khi chọn evidence. Các số liệu trong
sách được hiểu theo phiên bản tài liệu, không xem là thông tin hiện hành.

Nguồn, giấy phép, SHA-256 và metadata: `../data/manifest.json`.
Cách chạy và kiểm tra dữ liệu: `../data/README.md`.
