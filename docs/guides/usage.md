# Panduan Penggunaan - Hound Agent

Hound Agent mengumpulkan dan menganalisis kegagalan CI/CD/build/test, memperkirakan
root cause, melakukan triage, menyimpan report, dan membuat draft ticket.
Workflow utama tersedia melalui TUI interaktif dan CLI untuk automation/CI.

## 1. Instalasi

### Jalur 1: Menggunakan uv tool (Rekomendasi End-User, tanpa clone)

```sh
uv tool install hound-agent
hound --version
hound doctor
```

Untuk upgrade atau uninstall:

```sh
uv tool upgrade hound-agent
uv tool uninstall hound-agent
```

### Jalur 2: Menggunakan pipx

```sh
pipx install hound-agent
hound --version
```

### Jalur 3: Docker

```sh
docker run --rm -v ${PWD}:/work -w /work ghcr.io/youthisss/hound-agent:latest analyze /work/ci-logs
```

### Jalur 4: Setup Kontributor (Clone Repo)

```sh
git clone https://github.com/youthisss/hound-agent.git
cd hound-agent
uv sync --extra dev
uv run hound --version
```

## 2. TUI Default

Jalankan tanpa argumen dari terminal interaktif:

```sh
uv run hound
```

Hound Agent membuka TUI hanya jika stdin dan stdout merupakan TTY. Dalam pipe,
redirect, atau CI non-interaktif, command tanpa argumen berhenti dengan exit
`2` dan menyarankan:

```sh
hound analyze <log-directory>
```

Hound Agent tidak otomatis menganalisis current working directory saat command
kosong.

Untuk mengaudit payload LLM tanpa menghubungi provider, gunakan
`hound analyze --log failure.log --llm-preview`. Hound menulis request final yang
sudah dibatasi dan diredaksi ke `llm-preview.json`, lalu memakai analisis fallback
lokal untuk report.

TUI juga dapat dibuka eksplisit:

```sh
uv run hound tui --logs ./ci-logs --out hound-agent-output --offline
uv run hound tui --logs ./ci-logs --online --jobs 4 --max-llm-calls 20
```

Jika `--logs` tidak diberikan, TUI memakai `.hound-agent/logs` bila directory
hasil collector tersebut tersedia; selain itu TUI membuka current directory.

### Workflow TUI

TUI dibuka pada halaman **Home** dengan wordmark HOUND, readiness directory dan
provider, quick start, shortcut utama, serta rekomendasi setup. `Overview` kini
merupakan tab hasil pertama sejajar dengan `Report`, `Ticket`, dan `Raw log`.

1. Tombol `Settings [s]` berada di sidebar setelah daftar Recent Runs dan dapat dibuka kapan saja dengan `s`.
2. Pilih directory melalui tombol `Browse folder` atau tekan `b`; path juga dapat diketik manual.
3. Tekan `Load directory` setelah mengetik path manual.
4. Gunakan filter nama log bila perlu.
   Filter jenis (`Deploy`, `Build`, `Test`, `CI`, `Unknown`) dan sort berdasarkan
   waktu, jenis, atau nama dapat digabungkan. `Analyze all visible` hanya
   memproses artifact yang lolos filter aktif.
5. Pilih file `.log` dan jalankan `Analyze` atau tekan `a`.

UI menampilkan jumlah file dan path aktif. Analyze disabled jika directory atau
log tidak valid. Saat analisis berjalan, tombol menampilkan progress estimate
dan submit ganda diblokir.

`Analyze all visible` mendukung bounded parallelism melalui `--jobs`. Dalam mode
online, gunakan `--max-llm-calls` sebagai batas panggilan keras dan
`--max-cost-usd` sebagai guardrail estimasi biaya. Ringkasan batch TUI menampilkan
jumlah panggilan, artifact yang dilewati budget, dan estimasi biaya.

Tab tetap tersedia:

- `Overview`: severity, failed stage, root cause, confidence, durasi/timestamp,
  dan recommended action.
- `Report`: report Markdown.
- `Ticket`: draft ticket.
- `Raw log`: isi log aktif.
- `Settings`: provider, model, API key override, base URL, dan mode.

`Recent runs` menampilkan nama run, umur relatif, severity/status, dan ringkasan
failure. Daftar memiliki scrollbar vertikal; pilih run untuk memperbarui
Overview, Report, Ticket, dan Raw log.

State TUI eksplisit: empty, loading, success, dan error. Error analysis
menampilkan opsi retry.

### Shortcut TUI

| Tombol | Aksi |
|---|---|
| `a` | Analyze atau retry |
| `b` | Buka pemilih folder untuk log directory |
| `r` | Refresh log dan recent runs |
| `s` | Buka Settings dan fokus provider |
| `o` | Toggle offline mode |
| `Enter` | Buka log yang dipilih |
| `c` | Copy Report pada konteks relevan |
| `e` | Copy Ticket pada konteks relevan |
| `?` | Buka help overlay |
| `Esc` | Tutup overlay atau lepas focus |
| `q` | Quit |

Shortcut bar bawah berubah mengikuti tab/konteks aktif.

### Provider dan Model

Settings mendukung 9Router lokal pada `http://127.0.0.1:20128/v1` dan custom
provider OpenAI-compatible. `Connect & discover` menguji endpoint `/models`,
menyimpan API key ke keyring sistem operasi, dan memuat katalog model. Definisi
custom provider bersifat global; project YAML hanya memilih provider dan model.
HTTP hanya diterima untuk endpoint loopback, sedangkan endpoint remote wajib HTTPS.

## 3. Mengumpulkan Log

`hound log` membuat file log reusable dari command atau piped stdin.

### Jalankan Command

```sh
hound log -- npm test
hound log -- pytest -q
hound log -- docker build .
hound log --name unit-tests -- pytest -q
```

Command dijalankan langsung tanpa shell. stdout dan stderr digabung, ditampilkan
live ke terminal, lalu disimpan. Exit code child command dipertahankan.

### Ambil Piped Input

```sh
kubectl logs deployment/api | hound log --name api
npm test 2>&1 | hound log --name npm-test
kubectl rollout status deployment/api 2>&1 | hound log --name api-rollout --analyze --offline
```

Tanpa command dan tanpa piped stdin, collector berhenti dengan exit `2`.
Piped stdin kosong juga ditolak.

### Lokasi Output Collector

Default:

```text
.hound-agent/logs/
|- 20260811T143012Z-npm.log
`- 20260811T143012Z-npm.json
```

Atur destination:

```sh
hound log --output captured.log -- npm test
hound log --output ./existing-directory -- npm test
```

`--output` menerima file berakhiran `.log` atau directory yang sudah ada.

File `.log`, metadata JSON, dan live terminal stream di-redact secara default.
Gunakan `--raw-console` hanya jika output terminal mentah benar-benar diperlukan. Metadata memuat source, nama,
command, exit code, timestamp, durasi, cwd, lokasi log, status redaction, branch,
commit, dan changed files. Value setelah flag umum seperti `--token`,
`--password`, `--secret`, dan `--api-key` disensor dalam metadata.

### Capture dan Analyze

```sh
hound log --analyze --offline -- npm test
hound log --analyze -- npm test
```

`--analyze` memakai shared analysis service yang sama dengan CLI, TUI, dan
server. Analysis tidak berjalan otomatis tanpa flag ini, sehingga collector
tidak membuat panggilan LLM tersembunyi.

Jika child command gagal, exit code child tetap dipertahankan. Jika child
berhasil tetapi analysis gagal, command keluar dengan exit `3`.

## 4. Analisis Directory

Command canonical menerima directory yang berisi file `.log`:

```sh
hound analyze ./ci-logs
hound analyze ./ci-logs --offline
hound analyze ./ci-logs --repo ./repo --out hound-agent-output
```

Gunakan `hound doctor` untuk memeriksa Python, konfigurasi, provider, output
directory, Git, dan tool operasional lokal tanpa menampilkan nilai credential:

```sh
hound doctor
hound doctor --json
hound config show --json
```

`config show` hanya melaporkan credential sebagai `configured` atau `missing`.

Scan hanya level langsung, tidak recursive. Format input yang didukung: `.log`,
JUnit `.xml`, SARIF, dan test-report `.json`. Directory harus ada, readable, dan
berisi minimal satu artifact yang didukung.

Legacy `analyze --log <file>` masih diterima untuk compatibility, tetapi tidak
ditampilkan dalam help dan bukan syntax yang direkomendasikan.

### Format Output CLI

```sh
hound analyze ./ci-logs --format text
hound analyze ./ci-logs --format json
hound analyze ./ci-logs --format markdown
hound analyze ./ci-logs --format json --output result.json
```

- `text`: severity, root cause, failed stage/kind, confidence, recommended action.
- `json`: satu object JSON valid tanpa progress/debug noise di stdout.
- `markdown`: ringkasan Markdown per run.
- `--output`: menulis formatted output ke file dan menjaga stdout kosong.
- Warning dan error selalu ditulis ke stderr.

Setiap log mendapat run directory terpisah:

```text
hound-agent-output/
|- run-a1b2c3d4e5f6/
|  |- report.json
|  |- report.md
|  `- ticket.md
|- run-f6e5d4c3b2a1/
|  |- report.json
|  |- report.md
|  `- ticket.md
`- .hound-agent/
   `- state.json
```

Run ID bersifat opaque (`run-<random>`) agar nama file yang mungkin mengandung
PII atau secret tidak bocor ke path output.

### Exit Code Analyze

| Code | Arti |
|---|---|
| `0` | Analisis selesai; tidak ada CI/CD/build/test failure yang dikenali |
| `1` | Analisis selesai; minimal satu failure ditemukan |
| `2` | Argumen, path, isi directory, atau konfigurasi invalid |
| `3` | Internal analysis atau output error |

Exit `1` merupakan hasil analisis valid, bukan crash aplikasi.

Contoh CI:

```sh
hound analyze ./artifacts/logs --offline --format json --output hound-agent.json
code=$?

if [ "$code" -eq 1 ]; then
  echo "Hound Agent menemukan CI failure"
elif [ "$code" -ge 2 ]; then
  exit "$code"
fi
```

### Offline Mode

`--offline` memaksa rule-based analysis lokal dan dedup file lokal. Mode ini
tidak menghubungi provider AI. Agar kontrak no-network
jelas, `--offline` tidak boleh digabung dengan `--gh`, `--jira`, `--gitlab`,
atau `--slack-webhook`.

### Analisis CD

Stage `deploy` mengenali kegagalan rollout/readiness Kubernetes, image pull,
Helm rollback, Terraform apply, migrasi, dan permission deployment. Fitur ini
hanya menganalisis log dan tidak pernah menjalankan deploy, retry, rollback,
atau perubahan infrastruktur.

### QA Intelligence & Test History

```sh
# Analisis dan klasifikasi artefak uji terhadap histori tersimpan
hound qa analyze ./artifacts/junit.xml --json

# Bandingkan dengan baseline commit spesifik untuk mendeteksi likely regression
hound qa analyze ./artifacts/junit.xml --baseline 5a3f2e1

# Import laporan uji ke history store
hound qa import ./artifacts/junit.xml --run-id run-101 --commit 5a3f2e1 --branch main
```

## 5. Melihat Stored Run

```sh
hound report <run-id>
hound report build-error --out hound-agent-output
hound report build-error --format json
hound report build-error --format markdown --output report.md
```

Command membaca `<out>/<run-id>/report.json`. Run ID harus berupa satu nama
directory dan tidak boleh keluar dari output root.

### Operasi Output

```sh
# buat template konfigurasi tanpa menimpa config yang ada
hound init

# daftar run yang tersimpan
hound list-runs --out hound-agent-output
hound list-runs --out hound-agent-output --json

# hapus seluruh output analysis, hanya dengan konfirmasi eksplisit
hound clean --out hound-agent-output --yes
```

## 6. Konfigurasi Model

Persist provider preset atau nama model ke YAML:

```sh
hound config set model gemini
hound config set model gpt-4o-mini
hound config set model llama3.1 --config ./config/hound_agent.yml
```

Jika value cocok dengan provider preset, Hound Agent menyimpan provider beserta
default model provider. Jika tidak, value disimpan sebagai model. Update YAML
dilakukan atomic dan mempertahankan section lain. API key tidak dicetak.

## 7. Engine Analisis

| Mode | Kapan dipakai | Network |
|---|---|---|
| LLM | Provider/key/base URL tersedia dan tidak memakai `--offline` | Ya |
| Fallback rule-based | `--offline`, provider tidak tersedia, atau LLM gagal | Tidak |

LLM menggunakan endpoint OpenAI-compatible. Pilih provider melalui CLI, YAML,
atau environment variables:

```sh
hound analyze ./ci-logs --provider groq --model llama-3.3-70b-versatile
hound list-providers
hound list-providers --json
```

Jika LLM gagal, pipeline dapat jatuh ke deterministic fallback dan tetap
menghasilkan report.

## 8. Opsi Analyze

| Opsi | Fungsi |
|---|---|
| `<log-directory>` | Directory berisi file `.log`; wajib |
| `--repo` | Git checkout untuk branch, commit, dan changed files |
| `--source-context` | Opt-in: lampirkan source di sekitar frame hanya untuk log tepercaya |
| `--out` | Artifact root; default `hound-agent-output` |
| `--format` | `text`, `json`, atau `markdown` |
| `--output` | File untuk formatted CLI output |
| `--offline` | Rule-based local analysis tanpa network |
| `--source-class` | Trust profile: `trusted_branch`, `fork_pr`, atau `local_artifact` (fail-closed) |
| `--config` | YAML config opsional |
| `--jobs` | Jumlah worker paralel (default 1 = sekuensial) |
| `--no-dedup` | Matikan persistensi dedup |
| `--no-redact` | Matikan redaction secret/PII |
| `--provider` | Provider preset |
| `--model` | Model override |
| `--base-url` | Base URL provider override |
| `--api-key` | API key override; environment lebih aman |
| `--gh` | Buat GitHub issue |
| `--jira` | Buat Jira issue |
| `--gitlab` | Buat GitLab issue |
| `--slack-webhook` | Kirim Slack alert |

## 9. Konfigurasi YAML

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.2
  timeout: 120
  max_tokens: 2048
  max_retries: 3
  max_concurrency: 4
  routing: all             # all | exclude-kinds (lewati LLM untuk kind di skip_kinds)
  skip_kinds: [flaky]
  pricing:                 # USD per juta token; dipakai --max-cost-usd dan telemetry
    default:
      prompt_per_mtok: 0.30
      completion_per_mtok: 1.50

redact: true

trust:
  source_class: local_artifact   # trusted_branch | fork_pr | local_artifact

components:
  "app/cart/*": "cart"
  "src/handlers/*": "payments"

dedup:
  state_file: "/path/ke/state.json"
  backend: "file"          # file | sqlite
  # backend: "sqlite"      # WAL store, atomic upsert, aman untuk worker paralel
  max_entries: 50000
  retention_days: 90
  reuse: true              # reuse root cause tersimpan untuk insiden berulang (default on)
  reuse_after_occurrences: 3

github:
  repo: "owner/name"

jira:
  url: "https://jira.example.com"
  project: "QA"
  token: ""

gitlab:
  url: "https://gitlab.example.com"
  project: "group/repo"
  token: ""

slack:
  webhook_url: "https://hooks.slack.com/services/..."
```

Gunakan `--config <file>` secara eksplisit. HoundAgent tidak memuat config dari
repo yang dianalisis karena isi repo diperlakukan sebagai input tidak tepercaya.
Simpan secret dalam environment variable, bukan YAML.

## 10. Environment Variables

| Variabel | Fungsi |
|---|---|
| `TH_API_PROVIDER` | Provider generic |
| `TH_API_KEY` | API key generic |
| `TH_BASE_URL` | Base URL generic |
| `TH_MODEL` | Model generic |
| `TH_TEMPERATURE` | Temperature |
| `TH_TIMEOUT` | Timeout request |
| `TH_MAX_TOKENS` | Token output maksimum |
| `TH_MAX_RETRIES` | Retry maksimum |
| `TH_NO_REDACT=1` | Matikan redaction |
| `TH_SOURCE_CLASS` | Trust profile override (`trusted_branch`/`fork_pr`/`local_artifact`) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | OpenAI preset |
| `GEMINI_API_KEY` / `GEMINI_MODEL` / `GEMINI_BASE_URL` | Gemini preset |
| `GROQ_API_KEY` / `GROQ_MODEL` / `GROQ_BASE_URL` | Groq preset |
| `OLLAMA_MODEL` / `OLLAMA_BASE_URL` | Ollama preset |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` | DeepSeek preset |
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_MODEL` / `AZURE_OPENAI_BASE_URL` | Azure preset |
| `CUSTOM_API_KEY` / `CUSTOM_MODEL` / `CUSTOM_BASE_URL` | Custom preset |
| `GH_TOKEN` / `GH_REPO` / `GH_API_BASE` | GitHub integration |
| `JIRA_URL` / `JIRA_PROJECT` / `JIRA_TOKEN` | Jira integration |
| `GITLAB_URL` / `GITLAB_PROJECT` / `GITLAB_TOKEN` | GitLab integration |
| `SLACK_WEBHOOK_URL` | Slack integration |

## 11. Batch Legacy

Command batch lama tetap tersedia:

```sh
hound batch --logs ./ci-logs --out hound-agent-output --offline
hound batch --logs ./single.log --out hound-agent-output --offline
hound batch --logs ./ci-logs --out out --jobs 4 --max-llm-calls 40 --max-cost-usd 5.0
```

Batch memakai shared dedup state dan menulis `summary-<batch-id>.json` serta
`usage-<batch-id>.json` (jumlah panggilan LLM, run yang di-reuse, run yang
di-skip karena budget, total token, estimasi biaya). `--max-llm-calls` membatasi
jumlah panggilan LLM secara ketat termasuk saat paralel. `--max-cost-usd`
membatasi estimasi biaya dan dapat melewati ambang oleh request yang sudah berjalan (butuh
`llm.pricing`); begitu batas tercapai, log berikutnya memakai analisis rule-based
dan ditandai `budget_skipped`. Run dan summary lama dipertahankan sebagai history
tanpa ditimpa. Untuk automation baru, gunakan `hound analyze <log-directory>`
karena format output dan exit code-nya lebih jelas.

## 12. Server Webhook

```sh
TH_SERVER_TOKEN='replace-with-a-strong-token' hound server \
  --host 127.0.0.1 --port 8123 --log-root ./trusted-logs
```

- `POST /analyze`: bearer auth wajib; JSON `{"log": "relative/path.log", "offline": false}`. Field `repo` hanya boleh `"."` jika server dimulai dengan `--repo-root`.
- `GET /health`: process liveness.
- `GET /jobs/<id>`: bearer auth wajib; status job asynchronous.

Server memakai bearer token dan hanya menerima bind loopback. Jika diteruskan
melalui reverse proxy, gunakan TLS dan jangan expose token melalui log.

## 13. Feedback

Feedback engineer untuk suatu run disimpan ke store terpisah dari dedup state,
direkam dengan audit metadata, dan **tidak pernah mengubah klasifikasi otomatis**.
Feedback yang sudah di-review dapat diekspor menjadi kandidat fixture regresi
melalui proses eksplisit.

```sh
# Rekam feedback untuk stored run (wajib --run-id)
hound feedback record --out hound-agent-output --run-id run-a1b2c3d4e5f6 \
  --usefulness useful \
  --kind-correct correct --severity-correct incorrect \
  --owner-correct correct --duplicate-correct correct \
  --actual-kind test_failure --actual-severity high \
  --actual-owner "@qa-team" --actual-outcome root_cause_confirmed \
  --review-status reviewed --reviewer "engineer@example.com"

# Ekspor semua feedback yang sudah di-sanitize
hound feedback export --out hound-agent-output

# Ekspor hanya yang di-review, format JSONL ke file
hound feedback export --out hound-agent-output --reviewed-only \
  --format jsonl --output reviewed.jsonl

# Ekspor kandidat fixture regresi (manifest manual, bukan auto-mutasi rule)
hound feedback export --out hound-agent-output --candidate-fixtures
```

Store feedback berada di `<out>/.hound-agent/feedback.sqlite3` (terpisah dari
`state.sqlite3`/`state.json` milik dedup). Setiap record menyimpan `run_id`,
`report_sha256`, `dedup_key`, rating usefulness/kind/severity/owner/duplicate,
`actual_*` outcome, `review_status`, `reviewer`, dan `created_at`. Nilai yang
dikenali sebagai secret di-redact sebelum disimpan. Export kandidat fixture
menandai `requires_manual_sanitized_artifact: true` — feedback tidak pernah
mengubah rule atau klasifikasi secara otomatis.

## 14. Trust Policy

Setiap analisis diberi **source class** yang menentukan kapabilitas mana yang
boleh berjalan. Tujuannya fail-closed: sumber yang tidak tepercaya tidak boleh
memicu source reading, enrichment, LLM, atau delivery.

| Source class | Source context | Enrichment | LLM | Delivery |
|---|---|---|---|---|
| `trusted_branch` | Ya | Ya | Ya | Ya |
| `local_artifact` | Ya | Ya | Ya | Ya |
| `fork_pr` | Tidak | Tidak | Tidak | Tidak |

Pilih secara eksplisit dengan `--source-class <name>`, YAML
`trust.source_class: <name>`, atau env `TH_SOURCE_CLASS`. Jika tidak diberikan,
Hound mendeteksi dari environment CI: event `pull_request`/
`pull_request_target` GitHub dengan head repo berbeda dari base repo, dan GitLab
merge request lintas project (`CI_MERGE_REQUEST_SOURCE_PROJECT_ID !=
CI_PROJECT_ID`) diklasifikasikan sebagai `fork_pr`. Event PR yang hilang atau
tidak lengkap juga dianggap tidak tepercaya.

Profil `fork_pr` memaksa offline (`llm.require` ditolak), redaction selalu aktif
(`redact: false` diabaikan), dan kapabilitas terlarang diblokir sebelum
pemanggilan connector mana pun. Contoh:

```sh
# Fork PR: semua kapabilitas opsional otomatis nonaktif
hound analyze ./ci-logs --source-class fork_pr --offline

# Eksplisit tepercaya
hound analyze ./ci-logs --source-class trusted_branch --repo . --source-context
```

Hasil keputusan tercatat di `meta.trust` pada report: `source_class`,
`source_context`, `enrichment`, `llm`, `delivery`.

## 15. QA History

Hound menyimpan hasil test lintas run ke **history store** SQLite agar pola
flaky/regresi bisa dihitung dari data, bukan asumsi. Store terpisah dari dedup
state: `<out>/.hound-agent/history.sqlite3`.

```sh
# Import bukti test (JUnit/XML, JSON report, atau log runner) ke history
hound qa import ./artifacts --run-id ci-123 --commit <sha> --branch main \
  --environment "os=linux;python=3.11" --out hound-agent-output

# Lihat statistik agregat satu test
hound qa stats tests/test_checkout.py test_cart_total --out hound-agent-output --json

# Riwayat mentah per run/attempt
hound qa history tests/test_checkout.py test_cart_total --out hound-agent-output

# Daftar test yang terlacak
hound qa tests --suite-prefix tests/ --out hound-agent-output

# Ekspor history sanitized untuk CI cache / shared volume
hound qa export --out hound-agent-output --output history.json

# Impor balik manifest ekspor ke store lain
hound qa import history.json --run-id seed --out /tmp/fresh-output
```

Catatan model:

- Identitas stabil adalah pasangan `(suite, leaf test)`; prefix runner
  (`path::test`, `class.method`, dsb.) dipangkas ke leaf sehingga test yang sama
  terlacak konsisten di semua runner (pytest, JUnit, Jest/Vitest, Go, RSpec,
  Cargo, dotnet).
- Satu baris per `(suite, test, run_id, attempt)`; retry/flaky JUnit otomatis
  menjadi baris `failed(1)` + `passed(2)`.
- Raw log tidak pernah disimpan; baris hanya mereferensikan `run_id` /
  `evidence_id`.
- Tanpa cukup data, query `stats` melaporkan `failure_rate: null` dan
  `insufficient_history: true` — jangan menebak dari satu sample.
- Retention prunes seluruh baris lama; agregat dihitung ulang dari baris yang
  tersisa sehingga tidak pernah korup:
  `hound qa import <path> --retention-days 90 --out <out>`.

## 16. Arsitektur Singkat

```text
command / piped stdin
        |
        v
collector -> redacted .log + metadata
        |
        v
shared service -> pipeline -> parse -> analyze -> triage -> output
        ^
        |
CLI / TUI / server
```

`service.analyze_log()` menjadi entry point adapter-facing. Service mendelegasi
ke satu core `pipeline.analyze()`, sehingga parsing, redaction, AI analysis,
triage, dedup, dan report generation tidak diduplikasi.

## 17. Contoh End-to-End

```sh
# Install
uv sync --extra dev

# Capture command; exit mengikuti command yang dijalankan
uv run hound log --name tests -- pytest -q

# Buka captured logs dalam TUI
uv run hound

# Atau analisis directory secara headless
uv run hound analyze .hound-agent/logs --offline --format json \
  --output hound-agent-result.json

# Lihat salah satu stored run
uv run hound report <run-id> --format text
```

## 18. Testing dan Build

```sh
uv run pytest
uv run python -m py_compile src/hound_agent/cli.py src/hound_agent/tui.py \
  src/hound_agent/service.py src/hound_agent/collector.py src/hound_agent/formatters.py
uv build
```

Baseline saat dokumen diperbarui: `421 passed, 5 skipped` pada Windows. Skip
khusus verifikasi permission bit POSIX. Test tidak melakukan live API call.

## 19. Dokumentasi Lain

- `README.md`: ringkasan dan quick start.
- `docs/prd.md`: product requirements.
- `docs/architecture.md`: struktur modul dan data flow.
- `docs/plans/`: roadmap and implementation plans.
- `docs/workflow.md`: definition of done dan verification gate.
