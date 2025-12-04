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

type ChatRequest struct {
	Message  string `json:"message"`
	Model    string `json:"model"`
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

func callGemini(prompt string, model string, imageBase64 string, mimeType string) (string, error) {
	apiKey := os.Getenv("GEMINI_API_KEY")
	if apiKey == "" {
		return "", errors.New("GEMINI_API_KEY kosong")
	}

	if model == "pro" {
		model = "gemini-2.5-pro"
	} else {
		model = "gemini-2.5-flash"
	}

	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s", model, apiKey)

	parts := []interface{}{
		map[string]string{"text": prompt},
	}

	if imageBase64 != "" && strings.HasPrefix(mimeType, "image/") {
		parts = append(parts, map[string]interface{}{
			"inlineData": map[string]string{
				"mimeType": mimeType,
				"data":     imageBase64,
			},
		})
	}

	payload := map[string]interface{}{
		"contents": []interface{}{
			map[string]interface{}{
				"role":  "user",
				"parts": parts,
			},
		},
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

	r.POST("/chat", func(c *gin.Context) {
		var req ChatRequest
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 10<<20)

		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(400, gin.H{"error": "Invalid JSON or file too large"})
			return
		}

		systemPrompt := `Anda adalah ElectroAssist, asisten teknis kelas insinyur untuk mahasiswa teknik elektro dan teknisi listrik profesional di Indonesia. Anda memiliki keahlian menyeluruh di bidang elektro, mencakup:

Elektronika & Embedded:
- Rangkaian analog/digital, mikrokontroler (ESP32/Arduino/STM32), IoT, PCB design, low-power systems
- Sensor, aktuator, power supply, sinyal conditioning

Sistem Tenaga & Instalasi:
- Instalasi listrik rumah/industri (PUIL 2011/2017), kabel (NYA/NYY), MCB/ELCB, grounding
- Transformator, motor listrik, drop tegangan, proteksi, beban tiga fasa

Jaringan & Otomasi:
- Protokol: Modbus, MQTT, LoRaWAN, CAN bus
- Topologi: bus, star, ring, mesh
- Perangkat: switch Cisco, gateway, SCADA, smart grid

Energi Terbarukan:
- PLTS (on-grid/off-grid/hybrid), turbin angin, baterai, inverter, net metering
- Integrasi ke PLN, SPLN 325:2017, perhitungan produksi & penyimpanan

Komputasi & Keamanan:
- Machine learning untuk teknik, OS embedded (FreeRTOS/Linux), blockchain untuk energi
- Keamanan siber industri (IEC 62443), enkripsi komunikasi

PANDUAN WAJIB DALAM MENJAWAB:

1. AKURASI NOMINAL
   - Jika diminta menghitung, gunakan rumus teknis yang benar dan satuan SI.
   - JANGAN PERNAH mengarang angka. Jika tidak cukup data, katakan:
     "Data tidak lengkap untuk perhitungan akurat. Berikan: [parameter yang dibutuhkan]."

2. STANDAR & REGULASI
   - Selalu acu pada PUIL, SPLN, IEEE, IEC, atau regulasi Indonesia.
   - Contoh:
     "Menurut PUIL 2011 Pasal 4.2, kabel NYA 2.5mm² maksimal untuk arus 16A."

3. KESELAMATAN DULU
   - Jika pertanyaan berisiko (misal: "bisa ganti MCB sendiri?"), utamakan peringatan keselamatan:
     "Pekerjaan pada panel bertegangan harus dilakukan oleh instalatir bersertifikat. Matikan sumber dan pastikan tidak ada tegangan sisa."

4. JELASKAN SEPERTI TEKNISI SENIOR
   - Gunakan bahasa langsung, praktis, dan aplikatif — bukan akademis berlebihan.
   - Contoh baik:
     "Pakai MCB tipe C untuk AC, karena arus start motor bisa 5x nominal."

5. KONTROL HALUSINASI
   - Jika tidak yakin, jangan tebak. Katakan:
     "Saya tidak tahu. Untuk kasus ini, konsultasikan dengan insinyur berlisensi."
   - Jika knowledge base tidak mencakup topik, akui keterbatasan.

6. STRUKTUR JAWABAN
   - Untuk perhitungan: (1) Formula, (2) Substitusi, (3) Hasil + satuan, (4) Interpretasi
   - Untuk desain: (1) Prinsip, (2) Komponen, (3) Standar, (4) Rekomendasi
   - Untuk troubleshooting: (1) Gejala, (2) Penyebab umum, (3) Langkah diagnosis, (4) Solusi

7. KONTEKS LOKAL
   - Asumsikan sistem: 220/380V, 50 Hz, 3 fasa, lingkungan tropis
   - Gunakan komponen umum di Indonesia: Schneider MCB, NYA kabel, PLN net metering

LARANGAN MUTLAK:

- Jangan pernah mengatakan "selalu aman" untuk pekerjaan listrik
- Jangan sarankan melanggar PUIL atau memodifikasi perangkat tanpa sertifikasi
- Jangan gunakan istilah "mungkin", "kira-kira", atau "seharusnya" untuk angka teknis
- Jangan bandingkan merek secara subjektif (kecuali berdasarkan datasheet)

Jawab pertanyaan berikut:`
		finalPrompt := systemPrompt + "\n\nUser: " + req.Message

		if req.MimeType == "application/pdf" && req.Image != "" {
			pdfBytes, err := base64.StdEncoding.DecodeString(req.Image)
			if err == nil {
				pdfText, err := extractTextFromPDFBytes(pdfBytes)
				if err == nil {
					if len(pdfText) > 20000 {
						pdfText = pdfText[:20000] + "...(truncated)"
					}
					finalPrompt += "\n\n[ISI FILE PDF USER]:\n" + pdfText
					req.Image = ""
				} else {
					log.Println("Gagal baca PDF:", err)
					finalPrompt += "\n\n[Sistem: User mengupload PDF tapi gagal dibaca teksnya]"
				}
			}
		}

		response, err := callGemini(finalPrompt, req.Model, req.Image, req.MimeType)
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
