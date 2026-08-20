# Panduan Penggunaan - Hound Agent

Hound Agent mengumpulkan dan menganalisis kegagalan CI/CD/build/test, memperkirakan
root cause, melakukan triage, menyimpan report, dan membuat draft ticket.
Workflow utama tersedia melalui TUI interaktif dan CLI untuk automation/CI.

## 1. Instalasi

Butuh Python >= 3.10 dan [uv](https://docs.astral.sh/uv/).

```sh
cd tracehound
uv sync --extra dev
uv run hound --version
```

Package juga menyediakan executable `hound` setelah di-install.

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

TUI juga dapat dibuka eksplisit:

```sh
uv run hound tui --logs ./ci-logs --out tracehound_output --offline
```

Jika `--logs` tidak diberikan, TUI memakai `.tracehound/logs` bila directory
hasil collector tersebut tersedia; selain itu TUI membuka current directory.

### Workflow TUI

1. Tombol `Settings [s]` berada paling atas sidebar, sebelum `WORKFLOW`.
2. Pilih directory melalui tombol `Browse folder` atau tekan `b`; path juga dapat diketik manual.
3. Tekan `Load directory` setelah mengetik path manual.
4. Gunakan filter nama log bila perlu.
5. Pilih file `.log` dan jalankan `Analyze` atau tekan `a`.

UI menampilkan jumlah file dan path aktif. Analyze disabled jika directory atau
log tidak valid. Saat analisis berjalan, tombol menampilkan progress estimate
dan submit ganda diblokir.

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
.tracehound/logs/
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
hound analyze ./ci-logs --repo ./repo --out tracehound_output
```

Scan hanya level langsung, tidak recursive. Saat ini format input yang didukung
hanya `.log`. Directory harus ada, readable, dan berisi minimal satu `.log`.

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
tracehound_output/
|- run-a1b2c3d4e5f6/
|  |- report.json
|  |- report.md
|  `- ticket.md
|- run-f6e5d4c3b2a1/
|  |- report.json
|  |- report.md
|  `- ticket.md
`- .tracehound/
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

## 5. Melihat Stored Run

```sh
hound report <run-id>
hound report build-error --out tracehound_output
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
hound list-runs --out tracehound_output
hound list-runs --out tracehound_output --json

# hapus seluruh output analysis, hanya dengan konfirmasi eksplisit
hound clean --out tracehound_output --yes
```

## 6. Konfigurasi Model

Persist provider preset atau nama model ke YAML:

```sh
hound config set model gemini
hound config set model gpt-4o-mini
hound config set model llama3.1 --config ./config/tracehound.yml
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
| `--out` | Artifact root; default `tracehound_output` |
| `--format` | `text`, `json`, atau `markdown` |
| `--output` | File untuk formatted CLI output |
| `--offline` | Rule-based local analysis tanpa network |
| `--config` | YAML config opsional |
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

redact: true

components:
  "app/cart/*": "cart"
  "src/handlers/*": "payments"

dedup:
  state_file: "/path/ke/state.json"
  backend: "file"       # satu-satunya backend yang didukung

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

Gunakan `--config <file>` secara eksplisit. Tracehound tidak memuat config dari
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
hound batch --logs ./ci-logs --out tracehound_output --offline
hound batch --logs ./single.log --out tracehound_output --offline
```

Batch memakai shared dedup state dan menulis `summary-<batch-id>.json`. Run dan
summary lama dipertahankan sebagai history tanpa ditimpa. Untuk automation
baru, gunakan `hound analyze <log-directory>` karena format output dan exit
code-nya lebih jelas.

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

## 13. Arsitektur Singkat

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

## 14. Contoh End-to-End

```sh
# Install
uv sync --extra dev

# Capture command; exit mengikuti command yang dijalankan
uv run hound log --name tests -- pytest -q

# Buka captured logs dalam TUI
uv run hound

# Atau analisis directory secara headless
uv run hound analyze .tracehound/logs --offline --format json \
  --output hound-agent-result.json

# Lihat salah satu stored run
uv run hound report <run-id> --format text
```

## 15. Testing dan Build

```sh
uv run pytest
uv run python -m py_compile tracehound/cli.py tracehound/tui.py \
  tracehound/service.py tracehound/collector.py tracehound/formatters.py
uv build
```

Baseline saat dokumen diperbarui: `246 passed, 1 skipped` pada Windows. Skip
khusus verifikasi permission bit POSIX. Test tidak melakukan live API call.

## 16. Dokumentasi Lain

- `README.md`: ringkasan dan quick start.
- `PRD.md`: product requirements.
- `ARCHITECTURE.md`: struktur modul dan data flow.
- `TODO.md`: roadmap.
- `WORKFLOW.md`: definition of done dan verification gate.
