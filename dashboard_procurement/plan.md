Rygell Dashboard: Integrated Procurement & Logistics Blueprint

1. Arsitektur Data & Pemetaan Template Excel

Sistem akan membagi data menjadi tiga kategori utama berdasarkan template yang Anda unggah: Dedicated Fix, Dedicated Var, dan Oncall.

Skema Database (PostgreSQL)

master_data: Mill, Vendor (Code & Name), Product, Origin/Destination Zone, MOT, UoM.

contracts_dedicated_fix: Menyimpan data biaya bulanan (Jan-Jun), License Plate, dan Distributed Cost.

contracts_dedicated_var: Menyimpan data rute, Payload, dan Cost/KG.

contracts_oncall: Menyimpan data rute, Loading/Unloading Cost, dan Running Cost (IDR/Ton/KM).

audit_logs: Menyimpan kolom "Update Terbaru" (siapa, kapan, dan isi kesepakatan terbaru/notes).

2. Fase I: Backend Development (Golang + Gin) - [STATUS: 95% DONE]

Fokus pada mesin parsing Excel yang kuat menggunakan library excelize.

Fitur Utama Backend:

[x] Dynamic Excel Parser:
    - Mendeteksi header template secara otomatis (Banten Area, Dedicated Fix, dll).
    - Validasi tipe data: Memastikan kolom biaya (IDR) adalah angka dan tanggal validitas valid.

[x] Calculation Engine:
    - Perhitungan otomatis Cost/KG/KM dan Running Cost berdasarkan input Distance dan Payload.

[x] History & Agreement Tracking:
    - Menyimpan histori kesepakatan vendor via Audit Logs. Setiap kali data diperbarui, data lama disimpan agar "Kesepakatan Terbaru" selalu muncul di dashboard utama.

[~] Export Service:
    - Menghasilkan file Excel pelaporan. (Backend ready, Frontend UI pending).

3. Fase II: Frontend Development (Next.js + Refine) - [STATUS: 100% DONE]

Membangun antarmuka yang memudahkan navigasi antara rute logistik dan perbandingan vendor.

Komponen Refine:

[x] Import Wizard:
    - User mengunggah file Excel -> Refine menampilkan pratinjau data -> User melakukan konfirmasi (Mapping).

[x] Resource Views:
    - Mill View: Detail lokasi dan daftar rute terkait.
    - Vendor View: Detail profil vendor & daftar armada.
    - Proposal/Oncall View: Tabel perbandingan harga antar vendor untuk rute yang sama.

[x] Update Agreement Column:
    - Setiap baris data memiliki tombol "Edit" untuk memasukkan catatan kesepakatan terbaru & audit history.

4. Fase III: Fitur Khusus Logistik (Rygell Exclusive) - [STATUS: 50% PROGRESS]

[ ] Distance Matrix Integration: Mengambil data dari sheet "LOKASI" untuk mengisi otomatis kolom Distance pada sheet Oncall. (Parsing ready, Lookup logic pending).

[x] Running Cost Monitor: Visualisasi efisiensi biaya (IDR/Ton/KM) antar vendor via Dashboard KPI.

[x] Validity Alert: Notifikasi/Kartu dashboard jika tanggal Validity End sudah dekat (< 30 hari).

5. Fase IV: Real-time & Kolaborasi - [STATUS: 10% PROGRESS]

[ ] WebSocket Sync: Update layar otomatis tanpa refresh saat ada perubahan data di staf lain.

[~] Conflict Resolution: Sistem saat ini menggunakan Upsert (Overwrite). Dialog pilihan manual "Overwrite" atau "Skip" belum ditambahkan.

6. Fase V: Deployment (VPS) - [STATUS: 100% DONE]

[x] Docker Compose: Container untuk rygell-api (Go), rygell-web (Next.js), dan postgres.

[x] Excel Storage: Folder `uploads/` untuk menyimpan arsip file Excel sebagai referensi audit.

---
**Catatan Pembaruan Terkini (Maret 2026):**
- Seluruh antarmuka (Dashboard, Form, List) telah melalui proses **Localization** ke Bahasa Inggris (dari sebelumnya Bahasa Indonesia).
- Styling Dark Mode telah dibersihkan (Custom Scrollbars, Logout button harmonization).
- Navigasi Dashboard sekarang langsung menuju halaman Edit untuk efisiensi workflow.


Rencana Eksekusi Teknis

Normalisasi Data: Memecah sheet "LOKASI" dan "List FA" menjadi tabel master di PSQL.

Bulk Insert Logic: Menggunakan fitur COPY atau batch insert di GORM untuk mempercepat impor ribuan baris dari Excel.

UI Consistency: Menggunakan Tailwind CSS untuk memastikan dashboard tetap responsif meskipun menampilkan tabel dengan banyak kolom (seperti sheet Dedicated Fix).