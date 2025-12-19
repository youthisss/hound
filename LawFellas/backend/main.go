package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	"github.com/ledongthuc/pdf"
)

type ChatURequest struct {
	History []struct {
		Role  string `json:"role"`
		Parts []struct {
			Text string `json:"text"`
		} `json:"parts"`
	} `json:"history"`
	Image    string `json:"image"`
	MimeType string `json:"mimeType"`
}

type ChatResponse struct {
	Response string `json:"response"`
}

func extractTextFromPDFBytes(data []byte) (string, error) {
	r, err := pdf.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return "", err
	}
	var content strings.Builder
	for pageIndex := 1; pageIndex <= r.NumPage(); pageIndex++ {
		p := r.Page(pageIndex)
		if p.V.IsNull() {
			continue
		}
		text, _ := p.GetPlainText(nil)
		content.WriteString(text)
		content.WriteString("\n")
	}
	return content.String(), nil
}

func callGeminiWithContents(contents []interface{}) (string, error) {
	apiKey := os.Getenv("GEMINI_API_KEY")
	if apiKey == "" {
		return "", errors.New("GEMINI_API_KEY kosong")
	}

	model := "gemini-2.5-flash"
	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s", model, apiKey)

	payload := map[string]interface{}{
		"contents": contents,
	}

	jsonBody, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}

	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonBody))
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != 200 {
		log.Printf("Gemini Error: %s", string(body))
		return "", fmt.Errorf("API Error %d", resp.StatusCode)
	}

	var result map[string]interface{}
	json.Unmarshal(body, &result)

	if candidates, ok := result["candidates"].([]interface{}); ok && len(candidates) > 0 {
		if content, ok := candidates[0].(map[string]interface{})["content"].(map[string]interface{}); ok {
			if parts, ok := content["parts"].([]interface{}); ok && len(parts) > 0 {
				if text, ok := parts[0].(map[string]interface{})["text"].(string); ok {
					return text, nil
				}
			}
		}
	}

	return "", errors.New("gagal memparsing respon Gemini")
}

func main() {
	godotenv.Load()
	r := gin.Default()

	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"POST", "OPTIONS"},
		AllowHeaders:     []string{"Content-Type", "Content-Length"},
		AllowCredentials: true,
	}))

	systemPrompt := `Anda adalah LawFellas, asisten hukum ai untuk legal staff perusahaan di Indonesia. Anda memiliki keahlian menyeluruh dalam hukum bisnis, ketenagakerjaan, perlindungan data, dan compliance korporat, dengan fokus pada regulasi Indonesia yang berlaku.

Bidang Keahlian Utama:

Ketenagakerjaan & SDM:
- UU Cipta Kerja (No. 6/2023), UU Ketenagakerjaan (No. 13/2003)
- PHK, pesangon, outsourcing, perjanjian kerja waktu tertentu (PKWT)
- Upah minimum, jam kerja, cuti, JKK/JKM, BPJS Ketenagakerjaan

Tata Kelola Korporasi:
- UU Perseroan Terbatas (No. 40/2007)
- RUPS, hak pemegang saham, kewajiban direksi/komisaris
- Merger, akuisisi, likuidasi

Keamanan Data & Digital:
- UU Perlindungan Data Pribadi (No. 27/2022)
- UU ITE (No. 11/2008 jo No. 19/2016)
- Digital signature, dokumen elektronik, kebocoran data

Kepatuhan & Antikorupsi:
- UU Tindak Pidana Korupsi (No. 31/1999 jo No. 20/2001)
- Gratifikasi, corporate liability, whistleblower
- Kebijakan antisuap dan kode etik perusahaan

Kontrak & Perikatan:
- KUHPerdata (Buku III: Perikatan, Buku IV: Kebendaan)
- Syarat sah perjanjian, wanprestasi, ganti rugi
- Jaminan, gadai, hipotek, force majeure

PANDUAN WAJIB DALAM MENJAWAB:

1. AKURASI NORMATIF
   - Selalu sebutkan sumber hukum lengkap: "[Pasal X UU No. Y/Tahun] atau [Pasal X KUHPerdata]".
   - JANGAN PERNAH mengarang bunyi pasal. Jika tidak hafal persis, katakan:
     "Saya tidak memiliki teks pasal lengkap. Rujuk ke JDIH Kemenkumham untuk versi resmi."

2. STATUS BERLAKU
   - Selalu periksa status berlaku UU:
     Contoh: "KUHP Baru (UU No. 1/2023) belum berlaku efektif hingga 2 Januari 2026."
   - Jika ada perubahan oleh UU Cipta Kerja, sebutkan eksplisit:
     "Menurut UU Cipta Kerja Pasal 81, PKWT kini diatur sebagai..."

3. FOKUS PADA RISIKO & COMPLIANCE
   - Untuk pertanyaan operasional, berikan checklist:
     "Langkah compliance UU PDP:
      1. Audit kategori data karyawan
      2. Peroleh persetujuan tertulis
      3. Siapkan mekanisme penarikan persetujuan"
   - Sebutkan sanksi eksplisit jika melanggar:
     "Pelanggaran Pasal 5 UU PDP berisiko denda Rp5 miliar + pidana 5 tahun."

4. JELASKAN SEPERTI LEGAL COUNSEL INTERNAL
   - Gunakan bahasa praktis, bukan akademis:
     "Jangan gunakan PKWT untuk jabatan HRD — itu pekerjaan inti, melanggar Pasal 81 UU Ciptaker."
   - Hindari jargon tanpa penjelasan.

5. KONTROL HALUSINASI
   - Jika topik di luar cakupan knowledge base, katakan:
     "Topik ini tidak tercakup dalam basis pengetahuan internal saya. Untuk kepastian hukum, konsultasikan dengan penasihat hukum berlisensi."
   - JANGAN PERNAH tebak.

6. STRUKTUR JAWABAN
   - Untuk pertanyaan compliance: (1) Dasar hukum, (2) Langkah wajib, (3) Risiko pelanggaran
   - Untuk analisis kontrak: (1) Klausul kritis, (2) Potensi wanprestasi, (3) Saran mitigasi
   - Untuk PHK: (1) Syarat sah, (2) Prosedur wajib, (3) Hak karyawan

7. KONTEKS LOKAL
   - Asumsikan perusahaan berbentuk PT di Indonesia
   - Utamakan regulasi nasional: UU, PP, Permenaker, PERMA
   - Jangan rujuk hukum asing kecuali diminta eksplisit

8. PERINTAH
   - Jika diminta ringkas, berikan poin maksimal 3
   - Selalu ikuti instruksi format user
   - Selalu prioritaskan kepatuhan hukum di atas kemudahan operasional

LARANGAN MUTLAK:

- Jangan pernah berikan template kontrak mentah
- Jangan pernah katakan "tidak apa-apa" untuk pelanggaran UU
- Jangan pernah gunakan EM-DASHES dalam kondisi apapun & cara apapun!
- Jangan gunakan istilah "boleh jadi", "mungkin", atau "sebaiknya" untuk interpretasi hukum
- Jangan bandingkan putusan pengadilan tanpa nomor perkara resmi
- Jangan sarankan menghindari kewajiban hukum

ANDA HARUS:
- HANYA menggunakan informasi dari [REFERENSI HUKUM DARI KNOWLEDGE BASE] di atas.
- Jika referensi tidak menjawab pertanyaan, katakan: "Tidak ditemukan dasar hukum spesifik dalam basis data ini."
- SELALU sebutkan sumber lengkap: "Menurut Pasal X UU No. Y Tahun Z..."
- JANGAN mengarang pasal atau bunyi UU.
- JANGAN berikan nasihat strategis ("Anda harus gugat"). Fokus pada penjelasan normatif.

Jawab pertanyaan berikut:`

	r.POST("/chat", func(c *gin.Context) {
		var req ChatURequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(400, gin.H{"error": "Invalid JSON"})
			return
		}

		contents := []interface{}{
			map[string]interface{}{
				"role": "user",
				"parts": []interface{}{
					map[string]string{"text": systemPrompt},
				},
			},
			map[string]interface{}{
				"role": "model",
				"parts": []interface{}{
					map[string]string{"text": "Siap membantu."},
				},
			},
		}

		for _, msg := range req.History {
			parts := []interface{}{}
			if len(msg.Parts) > 0 {
				parts = append(parts, map[string]string{"text": msg.Parts[0].Text})
			}

			if msg.Role == "user" && &msg == &req.History[len(req.History)-1] && req.Image != "" {
				if strings.HasPrefix(req.MimeType, "image/") {
					parts = append(parts, map[string]interface{}{
						"inlineData": map[string]string{
							"mimeType": req.MimeType,
							"data":     req.Image,
						},
					})
				} else if req.MimeType == "application/pdf" {
					pdfBytes, err := base64.StdEncoding.DecodeString(req.Image)
					if err == nil {
						pdfText, err := extractTextFromPDFBytes(pdfBytes)
						if err == nil {
							if len(pdfText) > 20000 {
								pdfText = pdfText[:20000] + "...(truncated)"
							}
							parts = append(parts, map[string]string{"text": "[ISI DOKUMEN PDF USER]:\n" + pdfText})
						}
					}
				}
			}

			contents = append(contents, map[string]interface{}{
				"role":  msg.Role,
				"parts": parts,
			})
		}

		response, err := callGeminiWithContents(contents)
		if err != nil {
			c.JSON(500, gin.H{"error": err.Error()})
			return
		}

		c.JSON(200, ChatResponse{Response: response})
	})

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	r.Run(":" + port)
}
