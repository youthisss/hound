# Plan Mutation Addendum — Causal Evidence Schema & Related Refinements

Status saat penulisan: **M4 (Normalized Test Results and Historical Store) selesai.**
Addendum ini mengikuti protokol Section 12 (Plan Mutation Protocol) pada dokumen utama.
Tidak ada milestone baru yang ditambahkan; tidak ada global invariant yang dilemahkan.

---

## 1. Discovery

Diskusi eksternal (causal chain tracing untuk cascading failure, out-of-order
execution, silent failure) mengidentifikasi bahwa **M7** dan **M11** sudah secara
konseptual mencakup kebutuhan ini, tapi task list M7 belum menspesifikasi **skema
wire format** untuk causal linking. Selain itu, dua task kecil relevan untuk M3
yang belum eksplisit tercatat.

**Milestone terdampak:** M3, M4 (catatan backlog non-blocking), M7, M8/M12 (catatan minor).
**Tidak ada milestone yang di-skip, dipecah, atau diurutkan ulang.**
**Tidak ada prerequisite milestone baru** — semua amendemen ini fit di dalam
dependency graph yang sudah ada (M3 sebelum M4/M7, M7 sebelum M9).

---

## 2. Amendemen ke M7 — Explicit Deployment Context and Timeline

**Alasan:** Task M7 saat ini menyebut "stable IDs and causal links from primary to
downstream events" tanpa menspesifikasi kontrak field. Tanpa ini, implementasi
causal linking berisiko ad-hoc per-connector, bertentangan dengan prinsip "one core
evidence model" di Section 1.

**Tambahan task (disisipkan setelah task "Expand failure events with stable IDs..."):**

- Spesifikasikan causal-link evidence dengan field eksplisit: `trace_id` (scope: satu
  eksekusi/request/pipeline run), `span_id`, `parent_span_id` (nullable — mendukung
  partial trace), `timestamp_ns` (opsional, presisi tinggi), `sequence` (fallback
  ordering saat timestamp tidak reliable atau resolusinya terlalu rendah untuk
  concurrency tinggi).
- Rekomendasikan (bukan wajibkan) keselarasan dengan **W3C Trace Context**
  (`traceparent` format) untuk `trace_id`/`span_id`, supaya evidence dari sistem yang
  sudah terinstrumentasi OpenTelemetry (relevan juga untuk trace connector di M9)
  bisa dipetakan tanpa transformasi tambahan.
- Definisikan secara eksplisit dua skema causal grouping yang berbeda level:
  - **Runtime/application-level**: `trace_id` per request/invocation.
  - **Pipeline/CI-level**: causal link mengikuti struktur job/step CI, bukan
    request-level. Timeline builder (task yang sudah ada di M7) harus menerima
    kedua bentuk ini melalui kontrak yang sama, bukan implementasi paralel.
- Tambahkan explicit **cycle detection** pada graph traversal (guard terhadap
  `parent_span_id` yang salah assign dari sisi instrumentasi user) dengan fallback
  aman: log warning + treat sebagai flat list, bukan fail total — konsisten dengan
  invariant "insufficient evidence is a valid result."
- Tambahkan fixture untuk **partial trace** (sebagian service belum terinstrumentasi)
  sebagai adversarial case di evaluator M1/M7, bukan dianggap kondisi error.

**Dampak ke Exit Criteria M7:** tidak berubah — tetap "Fixture deployments produce a
stable timeline and distinguish primary failure, downstream symptoms, recovery, and
unknown impact." Amendemen ini hanya memperjelas *bagaimana* linking dibangun secara
teknis, bukan menambah kriteria baru.

**Dampak ke M11 (validasi, tidak perlu amendemen):** M11 sudah scoped dengan benar
("static_candidate", strict depth limit, single pilot language) sebagai pelengkap
untuk kasus di mana runtime trace_id tidak tersedia. Tidak ada perubahan diperlukan.

---

## 3. Amendemen ke M3 — Feedback, Calibration, and Trust Policy

**Alasan:** Cost control terhadap LLM (disebut di Global Invariants dan berulang di
M9 "Token & Cost Control") akan lebih efektif kalau ada layer known-issue matching
sebelum LLM dipanggil sama sekali — bukan hanya dedup pasca-analisis.

**Tambahan task:**

- Tambahkan pengecekan **known-issue fingerprint match** terhadap feedback history
  (dari task feedback yang sudah ada) sebelum RCA engine memanggil LLM. Jika
  fingerprint (struktural, bukan hanya isi pesan) match dengan insiden yang sudah
  punya feedback/resolusi tercatat, kembalikan evidence tersebut langsung dan skip
  LLM call.
- Tambahkan **dry-run/preview mode** untuk LLM payload: sebelum evidence benar-benar
  dikirim ke provider, expose (via CLI flag, mis. `--llm-preview`) hasil setelah
  redaction untuk diaudit user. Ini memperkuat, bukan menggantikan, invariant
  "Secrets and PII are redacted before... LLM use" — memberi user cara verifikasi
  independen, bukan cuma percaya pada redaction step.

**Dampak ke Exit Criteria M3:** tidak berubah. Kedua task ini adalah penguatan trust
layer yang sudah jadi tujuan M3, bukan kriteria baru.

---

## 4. Catatan Backlog (bukan amendemen wajib, non-blocking)

### M4 — perluasan format test runner
M4 sudah selesai untuk cakupan JUnit, pytest, Jest/Vitest, Go, RSpec, Cargo, dotnet.
Dicatat sebagai perluasan bertahap **di masa depan, dalam scope M4 yang sudah ada**
(bukan milestone baru): E2E framework (Playwright, Cypress — termasuk kebutuhan
attachment screenshot/video on failure) dan load/performance test (k6, Locust —
konsep "failure" berbasis threshold breach, bukan pass/fail biasa). Tidak
memblokir M5/M6.

### M8/M12 — server auth granularity
Saat ini `HOUND_SERVER_TOKEN` bersifat single bearer token global. Untuk skala
multi-tim/multi-repo, dicatat sebagai kandidat hardening task di M12 (Delivery
Reliability): token granular per-team/per-repo untuk audit trail dan rate limit
per-tim. Tidak memblokir M8/M9.

---

## 5. Eksplisit Ditolak (agar tidak diusulkan ulang)

- **Suggested fix diff / auto-generated code patch** — bertentangan langsung dengan
  Non-Goals #1 ("Automatically modify source code or open fix PRs"). Ditolak
  berdasarkan Non-Goals, bukan opini.
- **Dashboard trend HTML/Grafana-style untuk end-user** — sudah cukup terwakili oleh
  kombinasi M4 query layer + M9 Prometheus connector (yang justru expose ke
  observability stack existing user, sesuai Non-Goals #3: "Replace observability
  platforms" — jangan bangun dashboard sendiri). Tidak ditambahkan sebagai task.
- **Full repository call graph / codebase-wide indexing** — bertentangan dengan
  Non-Goals #7 ("Build a public plugin ecosystem before internal connector
  contracts stabilize") secara semangat, dan dengan filosofi "modular monolith,
  bounded connectors" di Section 4. M11 versi bounded/single-language sudah cukup.
- **Auto-detect stack saat `hound init`** — nice-to-have DX, tidak cukup material
  untuk masuk milestone manapun saat ini; boleh dipertimbangkan lagi setelah M12
  (pilot feedback) kalau user pilot secara eksplisit memintanya.

---

## 6. Ringkasan Dampak terhadap Dependency Graph

```text
M1 -> M2 -> M3*  (amendemen: known-issue matching, LLM preview)
             |-> M4 (selesai; catatan backlog non-blocking)
             |-> M7*  (amendemen: causal event schema)  -> M9
             `-> M10 -> M11 (tidak berubah, sudah scoped benar)
```

Tidak ada perubahan pada urutan M5→M6 (jalur QA yang sedang berjalan setelah M4).
Amendemen M3 dan M7 tidak menghalangi progres M5/M6 saat ini karena berada di
jalur paralel yang berbeda (M3 sudah selesai sebagai prasyarat; M7 belum dimulai).
