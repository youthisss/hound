package services

import (
	"fmt"
	"strings"

	"github.com/xuri/excelize/v2"
)

// ParsedSheet represents data extracted from a single Excel sheet.
type ParsedSheet struct {
	SheetName string              `json:"sheet_name"`
	SheetType string              `json:"sheet_type"` // "dedicated_fix", "dedicated_var", "oncall", "location", "unknown"
	Headers   []string            `json:"headers"`
	Rows      []map[string]string `json:"rows"`
}

// ParserService handles Excel file parsing and template detection.
type ParserService struct{}

// NewParserService creates a new ParserService.
func NewParserService() *ParserService {
	return &ParserService{}
}

// ParseExcelFile reads an Excel file and returns structured data for each sheet.
func (s *ParserService) ParseExcelFile(filePath string) ([]ParsedSheet, error) {
	f, err := excelize.OpenFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to open excel file: %w", err)
	}
	defer f.Close()

	var sheets []ParsedSheet

	for _, sheetName := range f.GetSheetList() {
		parsed, err := s.parseSheet(f, sheetName)
		if err != nil {
			return nil, fmt.Errorf("failed to parse sheet '%s': %w", sheetName, err)
		}
		sheets = append(sheets, *parsed)
	}

	return sheets, nil
}

// parseSheet extracts headers and row data from a single sheet.
func (s *ParserService) parseSheet(f *excelize.File, sheetName string) (*ParsedSheet, error) {
	rows, err := f.GetRows(sheetName)
	if err != nil {
		return nil, err
	}

	if len(rows) == 0 {
		return &ParsedSheet{
			SheetName: sheetName,
			SheetType: "unknown",
		}, nil
	}

	// Detect header row (first non-empty row)
	headerIdx := -1
	for i, row := range rows {
		for _, cell := range row {
			if strings.TrimSpace(cell) != "" {
				headerIdx = i
				break
			}
		}
		if headerIdx >= 0 {
			break
		}
	}

	if headerIdx < 0 {
		return &ParsedSheet{
			SheetName: sheetName,
			SheetType: "unknown",
		}, nil
	}

	headers := rows[headerIdx]
	// Clean headers
	for i := range headers {
		headers[i] = strings.TrimSpace(headers[i])
	}

	// Detect sheet type based on headers
	sheetType := s.detectSheetType(headers, sheetName)

	// Parse data rows
	var dataRows []map[string]string
	for i := headerIdx + 1; i < len(rows); i++ {
		row := rows[i]
		rowMap := make(map[string]string)
		empty := true
		for j, header := range headers {
			if header == "" {
				continue
			}
			val := ""
			if j < len(row) {
				val = strings.TrimSpace(row[j])
			}
			if val != "" {
				empty = false
			}
			rowMap[header] = val
		}
		if !empty {
			dataRows = append(dataRows, rowMap)
		}
	}

	return &ParsedSheet{
		SheetName: sheetName,
		SheetType: sheetType,
		Headers:   headers,
		Rows:      dataRows,
	}, nil
}

// detectSheetType identifies the type of data in a sheet based on its headers and name.
func (s *ParserService) detectSheetType(headers []string, sheetName string) string {
	joined := strings.ToLower(strings.Join(headers, " "))
	nameLower := strings.ToLower(sheetName)

	// Priority 1: Check by sheet name first (most reliable)
	if strings.Contains(nameLower, "dedicated fix") || strings.Contains(nameLower, "fix cost") {
		return "dedicated_fix"
	}
	if strings.Contains(nameLower, "dedicated var") || strings.Contains(nameLower, "var cost") {
		return "dedicated_var"
	}
	if strings.Contains(nameLower, "oncall") || strings.Contains(nameLower, "on call") || strings.Contains(nameLower, "on-call") {
		return "oncall"
	}
	if strings.Contains(nameLower, "lokasi") || strings.Contains(nameLower, "location") {
		return "location"
	}

	// Priority 2: Check by headers
	// Dedicated Fix: monthly cost columns or license plate
	if strings.Contains(joined, "license plate") || strings.Contains(joined, "lisence plate") || strings.Contains(joined, "distributed cost") {
		return "dedicated_fix"
	}

	// Oncall: MUST check BEFORE dedicated_var because oncall sheets also have 'payload' and 'cost'
	if strings.Contains(joined, "running cost") || (strings.Contains(joined, "loading") && strings.Contains(joined, "unloading")) {
		return "oncall"
	}

	// Dedicated Var: payload + cost/kg
	if strings.Contains(joined, "payload") && (strings.Contains(joined, "cost/kg") || strings.Contains(joined, "cost per kg")) {
		return "dedicated_var"
	}

	return "unknown"
}

// ValidateRow checks individual row data for type correctness.
func (s *ParserService) ValidateRow(row map[string]string, sheetType string) []string {
	var errors []string

	// Validate cost fields are numeric where expected
	costFields := []string{
		"Cost Jan", "Cost Feb", "Cost Mar", "Cost Apr", "Cost May", "Cost Jun",
		"Distributed Cost", "Payload", "Cost/KG", "Running Cost",
		"Loading Cost", "Unloading Cost", "Distance",
	}

	for _, field := range costFields {
		if val, ok := row[field]; ok && val != "" {
			// Remove common separators and check if numeric
			cleaned := strings.ReplaceAll(strings.ReplaceAll(val, ",", ""), ".", "")
			cleaned = strings.ReplaceAll(cleaned, " ", "")
			if cleaned != "" {
				isNumeric := true
				for _, c := range cleaned {
					if c < '0' || c > '9' {
						isNumeric = false
						break
					}
				}
				if !isNumeric {
					errors = append(errors, fmt.Sprintf("field '%s' has non-numeric value: '%s'", field, val))
				}
			}
		}
	}

	return errors
}
