# Panduan Penggunaan - Hound

Hound mengumpulkan dan menganalisis kegagalan CI/CD/build/test, memperkirakan
root cause, melakukan triage, memvalidasi integritas report, menyimpan report,
merekam feedback terevaluasi, dan membuat draft ticket.
Workflow utama tersedia melalui TUI interaktif bermodel terminal monochrome dan
CLI untuk automation/CI.

---

## 1. Instalasi

Hound mendukung Python 3.10-3.12 pada Windows dan Linux. Sampai rilis pertama
`hound-tracer` tersedia di PyPI, gunakan commit yang telah direview berikut agar
package manager tidak memasang proyek lain yang menggunakan nama `hound`:

### Jalur 1: Menggunakan uv tool (Rekomendasi End-User, tanpa clone)

```sh
uv tool install "hound-tracer @ git+https://github.com/youthisss/hound-tracer.git@e0a640effda889427598b0cdb5bdd41d9749045c"
hound --version
hound doctor
```

Untuk upgrade atau uninstall:

```sh
uv tool upgrade hound-tracer
uv tool uninstall hound-tracer
```

### Jalur 2: Menggunakan pipx

```sh
pipx install "hound-tracer @ git+https://github.com/youthisss/hound-tracer.git@e0a640effda889427598b0cdb5bdd41d9749045c"
hound --version
hound doctor
```

### Jalur 3: Docker

```sh
docker run --rm -v ${PWD}:/work -w /work ghcr.io/youthisss/hound-tracer:latest analyze /work/ci-logs
```

### Jalur 4: Setup Kontributor (Clone Repo)

```sh
git clone https://github.com/youthisss/hound-tracer.git
cd hound-tracer
uv sync --extra dev
uv run hound --version
```

---

## 2. TUI Terminal Monochrome

Jalankan tanpa argumen dari terminal interaktif:

```sh
uv run hound
```

Hound membuka TUI hanya jika stdin dan stdout merupakan TTY. Dalam pipe,
redirect, atau CI non-interaktif, command tanpa argumen berhenti dengan exit
`2` dan menyarankan:

```sh
hound analyze <log-directory>
```

TUI juga dapat dibuka eksplisit:

```sh
uv run hound console --logs ./ci-logs --output-dir hound-output --offline
uv run hound console --logs ./ci-logs --online --jobs 4 --max-llm-calls 20
```

### Prinsip Visual & Desain Monochrome

TUI Hound Tracer mengikuti prinsip terminal monochrome ketat dan `antislop-ui`:
- Tidak menggunakan emoji dekoratif, gradient buatan, atau rounded pill borders.
- Palet warna berpusat pada hitam-putih kontras tinggi (`#000000`, `#ffffff`, `#f0f6fc`, `#8f8f8f`, `#30363d`).
- Aksen warna dibatasi murni untuk semantik status operasional:
  - `[green]`: Status `PASS`, berhasil, verifikasi integritas valid.
  - `[yellow]`: Status `WARN`, peringatan advisory, report stale.
  - `[red]`: Status `FAIL`, pelanggaran policy, crash, atau credential leak terdeteksi.
  - `[dim]`: Teks metadata sekunder dan timestamp.

### Navigasi Workspace & Shortcut

| Tombol | Workspace / Aksi | Deskripsi |
|---|---|---|
| `a` / `A` | Analyze / Batch All | Jalankan analisis pada artefak terpilih atau seluruh list |
| `f` | Artifacts Workspace | Manajemen file log mentah, multi-select, dan batching |
| `l` | Results Workspace | Riwayat analisis per-run, filter stage, dan sorting |
| `y` | Quality Workspace | Evaluasi Quality Gate rilis, flakiness tracking, dan histori test |
| `i` | Context Workspace | Audit integritas report, boundary trust, dan timeline read-only |
| `u` | Validate Context | Jalankan validasi integritas report di disk dan simpan ke store |
| `v` | Record Feedback | Dialog feedback terisolasi untuk reviewer manusia |
| `c` | Copy Summary | Salin markdown ringkasan validasi (Context) atau Report (Results) |
| `b` / `r` | Browse / Refresh | Pilih direktori baru atau refresh scan artefak di disk |
| `m` / `s` | Sidebar / Settings | Toggle sidebar minimalis atau buka dialog konfigurasi provider |
| `z` / `d` | Select / Deselect All | Tandai seluruh artefak/hasil untuk aksi massal |
| `p` / `n` | Prev / Next Page | Paginasi daftar artefak dan hasil analisis |
| `x` / `X` | Clear Selected / All | Hapus run hasil tersimpan secara selektif atau menyeluruh |
| `o` | Toggle Offline | Ganti mode antara rule-based offline dan online AI provider |
| `esc` / `?`| Back / Help | Kembali ke layar sebelumnya atau buka bantuan panduan shortcut |

---

## 3. Quality & Gates Workspace (`y`)

Workspace Quality difokuskan pada pengujian deterministik dan penjagaan rilis:

1. **3-Tier Status Cards:**
   - **Test History Database:** Menampilkan kesiapan SQLite store (`.hound/history.sqlite3`), jumlah total run, dan rasio lulus/gagal dalam jendela 90 hari.
   - **Release Quality Gate:** Status evaluasi gate (`PASS`, `BLOCK`, atau status policy), status penegakan (`enforced` vs `advisory`), serta jumlah pelanggaran threshold.
   - **Regression Signal:** Deteksi flakiness aktif dan regresi performa/kegagalan test baru dari run terakhir.
2. **Active Policy Preview:**
   Menampilkan pratinjau aturan gate aktif dari berkas `quality.yml`/`quality.json` sebelum gate dijalankan, mencakup threshold coverage delta, batasan keparahan SARIF, dan toleransi flakiness.
3. **Aksi Quality Workspace:**
   - *Analyze test evidence:* Mengklasifikasikan kegagalan dari JUnit XML / JSON report.
   - *Import to history:* Memasukkan hasil run baru ke database histori test.
   - *Run quality gate:* Mengevaluasi kepatuhan rilis terhadap policy deterministik.
   - *Load history:* Menampilkan browser interaktif untuk seluruh test yang terlacak.

---

## 4. Context & Integrity Workspace (`i`)

Workspace Context bersifat **strictly read-only** untuk verifikasi forensik dan audit kepatuhan:

1. **Integritas Report (Report Integrity):**
   - Menghitung digest SHA-256 dari berkas `report.json` di disk.
   - Menandai status `STALE` jika berkas `report.json` diubah setelah validasi dijalankan.
   - Menolak eksekusi mutasi atau panggilan jaringan eksternal apa pun selama validasi.
2. **Audit Trust & Kapabilitas (Trust & Capabilities):**
   - Memeriksa fail-closed trust policy (`trusted_branch`, `local_artifact`, `fork_pr`).
   - Sumber `fork_pr` diverifikasi tidak memicu eksekusi LLM, pembacaan source context repositori internal, atau delivery tiket eksternal.
3. **Dampak Operasional (Operational Impact):**
   - Menampilkan tingkat keparahan efektif (`critical`, `high`, `medium`, `low`), dampak pelanggan (`customer_impact`), dan sisa SLO error budget.
4. **Integrity Checks & Audit Breakdown:**
   - Verifikasi skema `report.json` v2.0.
   - Verifikasi timeline kausalitas bebas siklus (DAG acyclic check).
   - Pemindaian kebocoran credential pada connector audit (token, secret, private keys).
   - Audit kelengkapan jejak observabilitas dan delivery ledger.
5. **Aksi Konteks:**
   - Tekan `u` atau klik `Validate report (u)` untuk menjalankan validasi penuh dan menyimpannya ke `.hound/validations.sqlite3`.
   - Tekan `v` atau klik `Record feedback (v)` untuk membuka modal feedback yang telah di-gate oleh status validasi.
   - Tekan `c` atau klik `Copy summary` untuk menyalin hasil audit ke clipboard dalam format markdown siap-tinjau.

---

## 5. Report Validation Engine & Persistence

Hound Tracer menyediakan engine validasi persistensi formal (`src/hound/validation.py`) yang menyimpan setiap verifikasi ke SQLite:

- **Lokasi Store:** `<output-dir>/.hound/validations.sqlite3` (dengan mode SQLite WAL dan pencadangan jika berkas korup).
- **Format Identifikasi:** `val-<12-hex>` unik per pemeriksaan.
- **Deteksi Stale:** Verifikasi membandingkan `report_sha256` tersimpan dengan hash aktual dari `report.json` saat ini.

### Struktur Tabel `validations`

```sql
CREATE TABLE IF NOT EXISTS validations (
    validation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    report_path TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL,       -- 'PASS', 'WARN', 'FAIL'
    summary TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

---

## 6. Feedback Gating & Reviewer Isolation

Feedback teknis engineer dicatat secara terpisah dari deduplication cache dan **tidak pernah mengubah classifier otomatis atau rule produksi**.

### Aturan Feedback Gate

Untuk menjamin kualitas dataset dan audit masa depan, Hound menerapkan gate ketat:
- Hanya report dengan status validasi **`PASS`** atau **`WARN`** yang dapat diberi status `review_status = 'reviewed'`.
- Jika report berstatus **`FAIL`** atau telah diubah di disk (berstatus **`STALE`**), upaya menyimpan feedback sebagai `'reviewed'` akan **ditolak** dengan error eksplisit (`ValueError`).

### CLI Feedback

```sh
# Merekam feedback dengan validasi terkait dan catatan audit
hound feedback record --output-dir hound-output --run-id run-a1b2c3d4e5f6 \
  --usefulness useful \
  --kind-correct correct \
  --severity-correct correct \
  --owner-correct correct \
  --duplicate-correct correct \
  --actual-outcome root_cause_confirmed \
  --review-status reviewed \
  --reviewer "lead-qa@example.com" \
  --validation-id val-8f92a1b0c3d4 \
  --root-cause-correction "Database connection pool exhausted under concurrent test load" \
  --notes "Verified via Jaeger trace spans; recommended bump in max pool size"

# Ekspor feedback yang telah di-review untuk analisis QA
hound feedback export --output-dir hound-output --reviewed-only \
  --format jsonl --output reviewed-feedback.jsonl
```

Flag CLI tambahan:
- `--validation-id`: ID verifikasi persistensi dari `.hound/validations.sqlite3`.
- `--root-cause-correction`: Koreksi manusia atas kesimpulan root cause AI.
- `--notes`: Catatan penjelasan reviewer untuk korelasi evaluasi masa depan.

---

## 7. Mengumpulkan Log (`hound log`)

`hound log` membuat file log reusable dari command atau piped stdin.

```sh
# Jalankan command langsung
hound log -- pytest -q
hound log --name payment-service -- npm test

# Ambil dari pipe
kubectl logs deployment/api | hound log --name api
npm test 2>&1 | hound log --name npm-test

# Tangkap dan langsung analisis secara offline
hound log --analyze --offline -- npm test
```

Nilai sensitif setelah token rahasia umum seperti `--token`, `--password`,
`--secret`, dan `--api-key` disensor secara otomatis dalam metadata dan stream
terminal mentah.

---

## 8. Analisis Directory (`hound analyze`)

Command utama untuk pipeline CI/CD:

```sh
# Analisis seluruh artefak di direktori secara offline
hound analyze ./ci-logs --offline

# Format JSON machine-readable
hound analyze ./ci-logs --offline --format json --output result.json

# Batasi biaya dan panggilan AI
hound analyze ./ci-logs --provider openai --max-llm-calls 10 --max-cost-usd 2.0
```

### Exit Codes

| Exit Code | Makna |
|---|---|
| `0` | Analisis selesai; tidak ditemukan kegagalan CI/CD/build/test |
| `1` | Analisis selesai; minimal satu kegagalan valid ditemukan |
| `2` | Parameter, path, atau format file input tidak valid |
| `3` | Internal error pada pipeline analisis atau output write failure |

---

## 9. Trust Boundary Architecture

| Source Class | Source Context | Enrichment | LLM Calls | Delivery Eksternal |
|---|---|---|---|---|
| `trusted_branch` | Ya | Ya | Ya | Ya |
| `local_artifact` | Ya | Ya | Ya | Ya |
| `fork_pr` | **Tidak** | **Tidak** | **Tidak** | **Tidak** |

Event PR dari repositori fork (`fork_pr`) mengaktifkan sandbox fail-closed:
- Panggilan LLM eksternal otomatis diblokir (`llm: false`).
- Pengambilan context repositori lokal dinonaktifkan (`source_context: false`).
- Pengiriman tiket ke GitHub/Jira/GitLab/Slack otomatis dibatalkan (`delivery: false`).
- Secret scrubbing / redaction dipaksa tetap aktif (`redact: true`).

---

## 10. Verifikasi & Testing

Jalankan suite verifikasi untuk memastikan seluruh gate terpenuhi:

```sh
# Verifikasi engine validasi report
uv run pytest tests/unit/test_validation.py

# Verifikasi feedback persistence & review gate
uv run pytest tests/integration/test_feedback.py

# Verifikasi TUI E2E workspace & status cards
uv run pytest tests/e2e/test_tui.py -k "test_tui_context_validation_persistence_and_cards or test_tui_context_stale_detection or test_tui_quality_workspace_cards_and_policy_preview or test_tui_feedback_modal_blocks_reviewed_on_failing_report"
```
