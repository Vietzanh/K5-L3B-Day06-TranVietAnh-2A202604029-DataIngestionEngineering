# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Chủ đề: External Debt – International Debt Report 2026.
  - Nguồn: The World Bank Group.
  - Tài liệu: `wb_idr_2026.pdf`.
  - Document ID: `wb-idr-2026`.
  - Tổng số trang PDF vật lý: 280.
  - Số trang nội dung được tính: 122.
  - Số trang được đưa vào indexing: 254.
  - Quyền sử dụng: Nguồn là báo cáo của World Bank Group. Tuy nhiên, license và quyền tái phân phối file PDF chưa được xác minh độc lập. Cần kiểm tra copyright/licence notice của tài liệu và điều khoản sử dụng của World Bank trước khi phân phối lại PDF.
  - Quy tắc đánh số trang: Sử dụng số trang PDF vật lý bắt đầu từ 1 làm `gold_page` và metadata `page`. Số trang in trên tài liệu được lưu riêng trong `printed_page`. Với tài liệu này, trang vật lý = trang in + 24 (đối với các trang có số trang in).

- **Chuẩn hóa, lỗi và giới hạn:**
  - Sử dụng Python và thư viện `pypdf` để trích xuất nội dung PDF.
  - Chuẩn hóa Unicode theo NFKC.
  - Loại bỏ một số ký tự vô hình như soft hyphen, zero-width space và BOM.
  - Chuẩn hóa tab, CRLF, khoảng trắng, xuống dòng; giữ lại cấu trúc dòng cần thiết.
  - Loại bỏ running header chứa tên báo cáo và số trang in ở phần đầu trang.
  - Sử dụng normalized matching để kiểm chứng evidence, bao gồm chuẩn hóa Unicode, chữ hoa/thường, dấu câu kiểu nháy, dấu gạch ngang và khoảng trắng.
  - Thống kê trích xuất:
    - `ok`: 263 trang.
    - `low_text`: 6 trang.
    - `empty`: 11 trang.
    - `error`: 0 trang.
  - Quy tắc tính trang nội dung: Chỉ tính trang có trạng thái `ok`, tối thiểu 200 ký tự, thuộc các loại `foreword`, `key_takeaways`, `analysis`, `appendix`; không tính trang có nội dung đầu tiên là Notes hoặc References.
  - Quy tắc indexing: Đưa vào indexing những trang có trạng thái `ok` hoặc `low_text`, có nội dung văn bản và không thuộc `front_matter` hoặc `back_matter`.
  - PDF là tài liệu born-digital, pipeline không sử dụng OCR. Các trang rỗng hoặc ít văn bản được ghi nhận trong `page_extraction_log.json` thay vì âm thầm bỏ qua.
  - Giới hạn: Cách phân loại chương/mục hiện dựa trên layout và khoảng trang được khai báo trong code, chưa phải hệ thống tự động nhận diện cấu trúc tài liệu tổng quát.

- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**
  - Embedding provider: OpenRouter.
  - Embedding model: `openai/text-embedding-3-small`.
  - Embedding dimensions: 1536.
  - Model version: Sử dụng model identifier trên; không ghi nhận một model snapshot/version ID riêng trong kết quả chạy.
  - Vector store: PostgreSQL + pgvector.
  - PostgreSQL: Major version 16.
  - pgvector: Docker image `pgvector/pgvector:0.8.7-pg16`, pgvector 0.8.7.
  - Distance metric: Cosine distance, sử dụng operator `<=>` của pgvector.
  - Search type: Exact vector search, không tạo approximate vector index.
  - Sử dụng cùng embedding model, số chiều, vector store và metric cho cả ba chiến lược.

  Lệnh thực thi trên Windows PowerShell:

  ```powershell
  cd starter

  python -m pip install -r requirements.txt

  docker compose -p day6_student_starter up -d --wait

  python scripts/check_setup.py

  python -m src.run --check-only

  python -m src.run
  ```

  - Thời điểm chạy: `2026-11-14 05:19:48 UTC`.
  - Embedding API requests: 32.
  - Tổng prompt tokens: 256,790.
  - Tổng tokens: 256,790.
  - Chi phí USD: Chưa xác định. API response không cung cấp thông tin chi phí đáng tin cậy (`cost_usd = null`); cần kiểm tra dashboard billing của OpenRouter.
  - Không sử dụng chi phí bằng 0 để thay thế cho giá trị chưa xác định.

- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - Metadata bắt buộc theo yêu cầu của lab:
    - `document_id`: ID định danh tài liệu (`wb-idr-2026`).
    - `source`: Đường dẫn tài liệu (`data/wb_idr_2026.pdf`).
    - `page`: Số trang PDF vật lý.
  - Các metadata bổ sung:
    - `printed_page`: Số trang in, được tính từ số trang PDF vật lý với offset 24.
    - `chapter`: Chương của tài liệu, xác định từ layout PDF.
    - `section`: Tên chương hoặc mục.
    - `section_type`: Loại nội dung như `analysis`, `appendix`, `foreword`, `key_takeaways`, `country_profile`.
    - `document_type`: `report`.
    - `year`: `2026`.
    - `language`: `en`.
    - Ngoài ra còn có các trường phục vụ ingestion và truy vết như `extraction_status`, `extraction_error`, `char_count`, `counted_as_content`, `indexed`.
  - Trường metadata được sử dụng cho filtering trong benchmark: `chapter`.
  - Nguồn giá trị: Khoảng trang được khai báo trong `LAYOUT` của `starter/src/ingestion.py`:
    - Chapter 1: trang PDF vật lý 27–74, giá trị `chapter = "1"`.
    - Chapter 2: trang PDF vật lý 75–106, giá trị `chapter = "2"`.
    - Chapter 3: trang PDF vật lý 107–134, giá trị `chapter = "3"`.
  - Lý do lựa chọn: Báo cáo được chia thành các chương có phạm vi trang rõ ràng. Lọc theo `chapter` giúp giới hạn phạm vi tìm kiếm vào đúng chương mà câu hỏi yêu cầu, đồng thời hỗ trợ kiểm soát phạm vi retrieval và giảm kết quả không liên quan.

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**

  | Strategy | Chunking        | Tham số               | Retrieval                                |
  | -------- | --------------- | --------------------- | ---------------------------------------- |
  | A        | Fixed-size      | 500 ký tự, overlap 80 | Dense vector search, không filter        |
  | B        | Paragraph-aware | Maximum 900 ký tự     | Dense vector search, không filter        |
  | C        | Paragraph-aware | Giống B               | Dense vector search + metadata filtering |
  - Strategy A: Chia văn bản thành các chunk có kích thước cố định 500 ký tự, overlap 80 ký tự.
  - Strategy B: Chia theo cấu trúc paragraph, giới hạn kích thước tối đa 900 ký tự.
  - Strategy C: Sử dụng cùng chunks và embeddings với B, chỉ bổ sung metadata filter khi câu hỏi có khai báo điều kiện lọc.
  - B và C chỉ khác nhau ở bước retrieval filtering. C không tạo một phương pháp chunking hoặc embedding mới.
  - Cả ba chiến lược sử dụng cùng corpus, embedding model, vector store và benchmark.

- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - Tổng số câu hỏi: 20.
  - Dev: 15 câu (q01–q15).
  - Test: 5 câu (q16–q20).
  - Câu hỏi được viết bằng tiếng Anh để phù hợp với ngôn ngữ của tài liệu nguồn.
  - Phương pháp chia tập: Topic-aware holdout.
    - Dev: Chapter 1, tập trung vào nội dung phân tích external debt, gold pages chủ yếu 27–34.
    - Test: Chapter 2, tập trung vào nội dung Debt Dynamics, gold pages 75–80.
  - Có 6 câu sử dụng metadata filter:
    - Dev: q11, q12, q13 với `chapter = "1"`.
    - Test: q18, q19, q20 với `chapter = "2"`.
  - Mỗi câu hỏi có `expected_answer`, `gold_source_id`, `gold_page` và `evidence_quote`.
  - Cách kiểm chứng evidence:
    - Đọc và trích xuất nội dung trang PDF nguồn.
    - Đối chiếu `gold_source_id` và `gold_page` với tài liệu và trang vật lý tương ứng.
    - Kiểm tra `evidence_quote` có thực sự xuất hiện trong nội dung trang sau chuẩn hóa.
    - Pipeline tự động kiểm tra evidence bằng normalized exact text matching trước khi chạy benchmark.
    - Khi đánh giá retrieval, một hit phải khớp document ID, physical page và chứa evidence quote đã chuẩn hóa trong chunk.
  - Với C, metadata filter được lấy từ `question.filter` và chỉ áp dụng khi câu hỏi có điều kiện filter. Không đưa gold source hoặc đáp án vào truy vấn.
  - Hạn chế của benchmark: Dev và test được chia theo chương, do đó test có thể phản ánh cả sự khác biệt chủ đề giữa Chapter 1 và Chapter 2. Test chỉ có 5 câu nên chưa đại diện đầy đủ cho toàn bộ tài liệu.

- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:**
  - Các artifact hiện tại chưa lưu lại bằng chứng về thời điểm chốt tiêu chí lựa chọn trước khi xem kết quả test. Vì vậy, không khẳng định tiêu chí đã được đăng ký trước thực nghiệm.
  - Tiêu chí dùng để diễn giải kết quả trong báo cáo:
    1. Ưu tiên Evidence Hit@3 trên dev.
    2. Tiếp theo là Hit@1 trên dev.
    3. Xem xét chunk coherence và grounding quality qua đánh giá thủ công.
    4. Xem xét khả năng metadata filtering và mức độ tuân thủ filter.
    5. So sánh số chunks, thời gian embedding, upsert và chi phí vận hành.
  - Test được sử dụng để báo cáo khả năng retrieval trên nhóm câu hỏi giữ lại, không phải để khẳng định tính tổng quát của chiến lược trên các tài liệu khác.

## Kết quả

### 1. Retrieval accuracy và tài nguyên

| Strategy | Split | Hit@1 (n/N)  | Evidence Hit@3 (n/N) | Chunk count | Thời gian                        | Chi phí       |
| -------- | ----- | ------------ | -------------------- | ----------: | -------------------------------- | ------------- |
| A        | Dev   | 7/15 (46.7%) | 9/15 (60.0%)         |       1,192 | Embedding 60.808s; upsert 1.079s | Chưa xác định |
| A        | Test  | 2/5 (40.0%)  | 2/5 (40.0%)          |       1,192 | Embedding 60.808s; upsert 1.079s | Chưa xác định |
| B        | Dev   | 9/15 (60.0%) | 12/15 (80.0%)        |         715 | Embedding 36.440s; upsert 0.630s | Chưa xác định |
| B        | Test  | 2/5 (40.0%)  | 3/5 (60.0%)          |         715 | Embedding 36.440s; upsert 0.630s | Chưa xác định |
| C        | Dev   | 9/15 (60.0%) | 12/15 (80.0%)        |         715 | Reuse embedding B; upsert 0.678s | Chưa xác định |
| C        | Test  | 2/5 (40.0%)  | 3/5 (60.0%)          |         715 | Reuse embedding B; upsert 0.678s | Chưa xác định |

Các thời gian dùng chung:

- PDF extraction: 5.560s.
- Chunking: 0.101s.
- Database schema setup: 0.029s.
- Query embedding: 2.169s.
- Total pipeline: 109.715s.

Thống kê chunk:

- A: 1,192 chunks, tổng 541,333 ký tự, trung bình 454.14 ký tự/chunk.
- B: 715 chunks, tổng 469,220 ký tự, trung bình 656.25 ký tự/chunk.
- C: 715 chunks, giống B.

Thời gian embedding của C không được tính riêng vì C sử dụng lại embeddings của B. Chi phí USD chưa có số liệu xác thực; tổng lần chạy ghi nhận 32 API requests và 256,790 tokens.

### 2. Đánh giá thủ công

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N)               | Filter tuân thủ (n/N hoặc N/A)              | Grounding 0/1/2 (số câu) và trung bình /2 |
| -------- | --------------------------- | --------------------------------------- | ------------------------------------------- | ----------------------------------------- |
| A        | Chưa chấm (10 mẫu)          | Chưa audit thủ công (tối đa 15 records) | N/A – không áp dụng filter                  | Chưa chấm (5 câu)                         |
| B        | Chưa chấm (10 mẫu)          | Chưa audit thủ công (tối đa 15 records) | N/A – không áp dụng filter                  | Chưa chấm (5 câu)                         |
| C        | Chưa chấm (10 mẫu)          | Chưa audit thủ công (tối đa 15 records) | 6/6 câu hỏi; 18/18 retrieved records (100%) | Chưa chấm (5 câu)                         |

Chi tiết thiết kế lấy mẫu:

- Chunk coherence: 10 trang nội dung được lựa chọn tương đối đều trên toàn bộ tập counted content pages. Mỗi vị trí so sánh một chunk tương ứng của A, B và C; tổng cộng tối đa 30 lượt chấm.
- Metadata audit: Kiểm tra các kết quả top-3 trên 5 câu test cho từng chiến lược, tối đa 15 records/strategy. Các trường được đối chiếu gồm document_id, source, page, chapter, section_type, printed_page, document_type, year và language.
- Grounding quality: Đánh giá 5 câu test cho mỗi chiến lược, tổng cộng 15 lượt chấm.
- Filter compliance: C có 6 câu hỏi sử dụng filter và 18 retrieved records được kiểm tra, tất cả đều thỏa mãn metadata condition.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**

- `starter/results/source_manifest.json`: Manifest của nguồn dữ liệu.
- `starter/results/page_extraction_log.json`: Log extraction từng trang.
- `starter/results/run_summary.json`: Thống kê metrics, thời gian, cấu hình và filter compliance.
- `starter/results/traces_A.json`: Trace top-3 của A.
- `starter/results/traces_B.json`: Trace top-3 của B.
- `starter/results/traces_C.json`: Trace top-3 của C.
- `starter/results/manual_review.json`: Các mẫu chunk coherence, grounding quality và metadata audit.

Các trường điểm và reviewer reason trong `manual_review.json` cần được hoàn thiện sau khi đọc và đánh giá thực tế. Các giá trị tự động về metadata consistency và filter compliance không thay thế đánh giá thủ công.

## Phân tích và kết luận

- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**

  **So sánh A và B:**

  Paragraph-aware chunking (B) cho kết quả tốt hơn fixed-size chunking (A) trong lần thực nghiệm này.

  Trên dev:
  - Hit@1 tăng từ 46.7% lên 60.0%, tăng 13.3 điểm phần trăm.
  - Evidence Hit@3 tăng từ 60.0% lên 80.0%, tăng 20 điểm phần trăm.

  Trên test:
  - Hit@1 giữ nguyên ở mức 40.0%.
  - Evidence Hit@3 tăng từ 40.0% lên 60.0%, tăng 20 điểm phần trăm.

  Bên cạnh đó, số lượng chunks giảm từ 1,192 xuống 715, tương đương giảm khoảng 40%. Tổng thời gian embedding giảm từ 60.808s xuống 36.440s trong lần chạy này.

  Kết quả cho thấy paragraph-aware chunking có lợi thế về retrieval accuracy và số lượng chunks trên corpus hiện tại. Một giả thuyết là phương pháp này giữ được cấu trúc và ngữ cảnh đoạn văn tốt hơn fixed-size chunking. Giả thuyết này cần được xác nhận thêm qua nhãn chunk coherence.

  **So sánh B và C:**

  B và C sử dụng cùng chunks, embeddings và embedding model nên khác biệt duy nhất là metadata filtering trong bước retrieval.

  Kết quả Hit@1 và Evidence Hit@3 của B và C giống nhau trên cả dev và test:
  - Dev: Hit@1 = 60%, Evidence Hit@3 = 80%.
  - Test: Hit@1 = 40%, Evidence Hit@3 = 60%.

  C đạt 100% metadata filter compliance:
  - 6/6 câu hỏi có filter tuân thủ hoàn toàn.
  - 18/18 retrieved records thỏa mãn điều kiện filter.

  Như vậy, metadata filtering không làm tăng retrieval accuracy trong benchmark hiện tại, nhưng giúp kiểm soát phạm vi tìm kiếm chính xác theo chương mà không làm giảm các chỉ số retrieval.

  **Hai ví dụ retrieval thất bại cần bổ sung từ trace thực tế:**
  1. Ví dụ 1:
     - Question ID: [Lấy từ traces_A/B/C.json]
     - Question: [Nội dung câu hỏi]
     - Gold source: `wb-idr-2026`.
     - Gold physical page: [Trang PDF].
     - Retrieved top-3: [Chunk ID và physical page].
     - Nguyên nhân: [Phân tích dựa trên nội dung top-3 và gold evidence].

  2. Ví dụ 2:
     - Question ID: [Lấy từ traces_A/B/C.json]
     - Question: [Nội dung câu hỏi]
     - Gold source: `wb-idr-2026`.
     - Gold physical page: [Trang PDF].
     - Retrieved top-3: [Chunk ID và physical page].
     - Nguyên nhân: [Phân tích dựa trên nội dung top-3 và gold evidence].

  Hai trường hợp cần được trích từ những câu có `evidence_hit_at_3 = false`, không tự suy đoán ID câu từ metrics tổng hợp.

- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - A phù hợp làm baseline đơn giản với fixed-size chunking, dễ triển khai và kiểm soát độ dài chunk. Tuy nhiên, số lượng chunks lớn hơn và retrieval metrics thấp hơn B trong thử nghiệm này.
  - B là lựa chọn phù hợp khi cần semantic retrieval thông thường, ưu tiên giữ cấu trúc đoạn văn và giảm số lượng chunks.
  - C phù hợp hơn khi hệ thống cần hỗ trợ người dùng giới hạn phạm vi tìm kiếm theo metadata như chương, năm hoặc loại tài liệu. C có kết quả retrieval tương đương B nhưng bổ sung khả năng kiểm soát phạm vi tìm kiếm.

  Với corpus hiện tại, B và C tốt hơn A về Evidence Hit@3. Nếu yêu cầu của hệ thống có metadata filtering, C là lựa chọn phù hợp hơn vì vừa duy trì retrieval metrics của B vừa đạt 100% filter compliance trong benchmark.

  Không kết luận C có retrieval accuracy cao hơn B chỉ vì có thêm metadata filtering. Hai chiến lược cho kết quả retrieval giống nhau trong lần chạy này.

- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - Corpus chỉ sử dụng một báo cáo PDF nên chưa thể khái quát kết quả cho nhiều loại tài liệu hoặc nhiều nguồn dữ liệu.
  - Benchmark gồm 20 câu hỏi, trong đó test chỉ có 5 câu. Một câu trả lời đúng hoặc sai tương ứng với 20 điểm phần trăm trên test, khiến metrics dễ biến động.
  - Dev và test được tách theo chương: dev thuộc Chapter 1, test thuộc Chapter 2. Topic shift có thể ảnh hưởng đến kết quả retrieval.
  - Gold evidence được đánh giá tự động bằng normalized exact quote matching. Cách này có thể bỏ sót chunk chứa bằng chứng tương đương về ngữ nghĩa nhưng không chứa nguyên văn evidence quote.
  - Chunk coherence, metadata usefulness và grounding quality chưa có nhãn thủ công tại thời điểm lập báo cáo này. Cần hoàn thành `manual_review.json` trước khi đưa ra kết luận cuối cùng về ba khía cạnh đó.
  - Metadata filter compliance 100% phản ánh việc các kết quả tuân thủ điều kiện lọc, không chứng minh toàn bộ kết quả đều chứa evidence đúng.
  - Thời gian chạy chỉ được đo trong một lần thực nghiệm, có thể bị ảnh hưởng bởi mạng, API provider, trạng thái database và môi trường thực thi.
  - Chi phí embedding thực tế chưa được xác định vì response API không cung cấp số liệu chi phí đáng tin cậy.
  - Pipeline hiện chỉ đánh giá retrieval và grounding của evidence, chưa đánh giá LLM Answer Generation, faithfulness của câu trả lời hoặc chất lượng câu trả lời cuối cùng.

- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  - Mở rộng corpus sang nhiều tài liệu cùng chủ đề để kiểm tra khả năng tổng quát hóa.
  - Tăng số lượng câu hỏi test, phân bố câu hỏi qua nhiều chương và nhiều loại nội dung để giảm ảnh hưởng của topic shift.
  - Bổ sung nhiều loại câu hỏi hơn như paraphrase, multi-hop reasoning, câu hỏi cần tổng hợp thông tin từ nhiều trang và câu hỏi có điều kiện.
  - Kiểm tra thủ công toàn bộ gold answer và evidence trước khi chạy benchmark; ghi nhận nhiều nguồn hợp lệ nếu có.
  - Hoàn thiện human evaluation với rubric thống nhất và có thể sử dụng hai người đánh giá độc lập để giảm thiên lệch.
  - Thử nghiệm thêm các giá trị chunk size và overlap, đồng thời tiếp tục giữ nguyên embedding model và benchmark khi so sánh từng yếu tố.
  - Mở rộng metadata filtering với các trường thực sự hữu ích như section, document_type, year và language.
  - Chạy nhiều lần để đánh giá tính ổn định của thời gian và chi phí.
  - Bổ sung BM25 hoặc hybrid retrieval để so sánh với dense retrieval.
  - Nếu mở rộng thành hệ thống RAG hoàn chỉnh, bổ sung LLM Answer Generation và đánh giá answer correctness, faithfulness và citation accuracy riêng biệt.
