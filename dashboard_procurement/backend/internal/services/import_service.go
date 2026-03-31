package services

import (
	"fmt"
	"log"
	"strconv"
	"strings"
	"time"

	"rygell-dashboard/internal/models"
	"rygell-dashboard/internal/repositories"

	"github.com/shopspring/decimal"
)

// ImportService handles the confirmation step of importing parsed Excel data into the database.
type ImportService struct {
	parserService *ParserService
	masterRepo    *repositories.MasterRepository
	contractRepo  *repositories.ContractRepository
}

// NewImportService creates a new ImportService.
func NewImportService(parser *ParserService, masterRepo *repositories.MasterRepository, contractRepo *repositories.ContractRepository) *ImportService {
	return &ImportService{
		parserService: parser,
		masterRepo:    masterRepo,
		contractRepo:  contractRepo,
	}
}

// ImportResult contains the summary of an import operation.
type ImportResult struct {
	DedicatedFixInserted int      `json:"dedicated_fix_inserted"`
	DedicatedVarInserted int      `json:"dedicated_var_inserted"`
	OncallInserted       int      `json:"oncall_inserted"`
	VendorsCreated       int      `json:"vendors_created"`
	MillsCreated         int      `json:"mills_created"`
	Errors               []string `json:"errors,omitempty"`
}

// ConfirmImport re-parses the saved Excel file and bulk-inserts data into the database.
func (s *ImportService) ConfirmImport(filePath string) (*ImportResult, error) {
	log.Printf("[IMPORT] Starting confirm import for file: %s", filePath)
	sheets, err := s.parserService.ParseExcelFile(filePath)
	if err != nil {
		log.Printf("[IMPORT] ERROR: Failed to re-parse file: %v", err)
		return nil, fmt.Errorf("failed to re-parse file: %w", err)
	}

	log.Printf("[IMPORT] Parsed %d sheets", len(sheets))
	result := &ImportResult{}

	for _, sheet := range sheets {
		log.Printf("[IMPORT] Sheet '%s' → type='%s', rows=%d, headers=%v",
			sheet.SheetName, sheet.SheetType, len(sheet.Rows), sheet.Headers)
		if len(sheet.Rows) > 0 {
			log.Printf("[IMPORT] First row sample: %v", sheet.Rows[0])
		}
		switch sheet.SheetType {
		case "dedicated_fix":
			count, errs := s.importDedicatedFix(sheet)
			log.Printf("[IMPORT] dedicated_fix: inserted=%d, errors=%d", count, len(errs))
			result.DedicatedFixInserted += count
			result.Errors = append(result.Errors, errs...)
		case "dedicated_var":
			count, errs := s.importDedicatedVar(sheet)
			log.Printf("[IMPORT] dedicated_var: inserted=%d, errors=%d", count, len(errs))
			result.DedicatedVarInserted += count
			result.Errors = append(result.Errors, errs...)
		case "oncall":
			count, errs := s.importOncall(sheet)
			log.Printf("[IMPORT] oncall: inserted=%d, errors=%d", count, len(errs))
			result.OncallInserted += count
			result.Errors = append(result.Errors, errs...)
		default:
			log.Printf("[IMPORT] Skipping sheet '%s' with unknown type '%s'", sheet.SheetName, sheet.SheetType)
		}
	}

	log.Printf("[IMPORT] Final result: fix=%d, var=%d, oncall=%d, errors=%v",
		result.DedicatedFixInserted, result.DedicatedVarInserted, result.OncallInserted, result.Errors)
	return result, nil
}

// resolveVendor finds or creates a vendor by name from a row.
func (s *ImportService) resolveVendor(row map[string]string) (uint, error) {
	name := findField(row, "TRANSPORTER/CARRIER", "Transporter/Carrier", "Vendor Name", "Vendor", "vendor_name", "VENDOR NAME", "TRANSPORTER")
	if name == "" {
		return 0, fmt.Errorf("vendor name is empty")
	}
	// Clean vendor name: sometimes it contains address after / or ,
	// e.g. "ALIEF SUKSES BERDIKARI, PT / BEKASI 17532" → use full string as name
	vendor, err := s.masterRepo.FindOrCreateVendorByName(name)
	if err != nil {
		return 0, err
	}
	return vendor.ID, nil
}

// resolveMill finds or creates a mill by name from a row.
func (s *ImportService) resolveMill(row map[string]string) (uint, error) {
	name := findField(row, "MILL/CATEGORY", "Mill/Category", "Mill", "Mill Name", "mill", "MILL")
	if name == "" {
		return 0, fmt.Errorf("mill name is empty")
	}
	mill, err := s.masterRepo.FindOrCreateMillByName(name)
	if err != nil {
		return 0, err
	}
	return mill.ID, nil
}

func (s *ImportService) resolveProduct(row map[string]string) (*uint, error) {
	name := findField(row, "PRODUCT", "Product")
	if name == "" {
		return nil, nil
	}
	product, err := s.masterRepo.FindOrCreateProductByName(name)
	if err != nil {
		return nil, err
	}
	return &product.ID, nil
}

func (s *ImportService) resolveZone(row map[string]string, columnNames ...string) (*uint, error) {
	name := findField(row, columnNames...)
	if name == "" {
		return nil, nil
	}
	zone, err := s.masterRepo.FindOrCreateZoneByName(name)
	if err != nil {
		return nil, err
	}
	return &zone.ID, nil
}

func (s *ImportService) resolveMot(row map[string]string) (*uint, error) {
	name := findField(row, "MOT", "Mode of Transport")
	if name == "" {
		return nil, nil
	}
	mot, err := s.masterRepo.FindOrCreateMotByName(name)
	if err != nil {
		return nil, err
	}
	return &mot.ID, nil
}

func (s *ImportService) resolveUom(row map[string]string) (*uint, error) {
	name := findField(row, "UOM", "UoM")
	if name == "" {
		return nil, nil
	}
	uom, err := s.masterRepo.FindOrCreateUomByName(name)
	if err != nil {
		return nil, err
	}
	return &uom.ID, nil
}

func (s *ImportService) importDedicatedFix(sheet ParsedSheet) (int, []string) {
	var contracts []models.ContractDedicatedFix
	var errs []string

	for i, row := range sheet.Rows {
		if isEmptyRow(row) {
			continue
		}
		vendorID, err := s.resolveVendor(row)
		if err != nil {
			if err.Error() == "vendor name is empty" {
				continue
			}
			errs = append(errs, fmt.Sprintf("Sheet '%s' row %d: %v", sheet.SheetName, i+2, err))
			continue
		}
		millID, err := s.resolveMill(row)
		if err != nil {
			if err.Error() == "mill name is empty" {
				continue
			}
			errs = append(errs, fmt.Sprintf("Sheet '%s' row %d: %v", sheet.SheetName, i+2, err))
			continue
		}

		motID, _ := s.resolveMot(row)
		uomID, _ := s.resolveUom(row)

		c := models.ContractDedicatedFix{
			VendorID:        vendorID,
			MillID:          millID,
			AreaCategory:    findField(row, "AREA/CATEGORY", "Area/Category", "Area"),
			ProposalCFAS:    findField(row, "PROPOSAL/CFAS", "Proposal/CFAS", "Proposal", "CFAS"),
			FANumber:        findField(row, "FA NUMBER", "FA Number", "FA No"),
			MotID:           motID,
			UomID:           uomID,
			LicensePlate:    findField(row, "LISENCE PLATE", "LICENSE PLATE", "License Plate", "license_plate", "Nopol"),
			SPKNumber:       findField(row, "SPK NUMBER", "SPK Number", "SPK", "spk_number", "SPK NO"),
			CostJan:         parseDecimal(findField(row, "Jan-26", "Jan-25", "Cost Jan", "Jan", "JAN")),
			CostFeb:         parseDecimal(findField(row, "Feb-26", "Feb-25", "Cost Feb", "Feb", "FEB")),
			CostMar:         parseDecimal(findField(row, "Mar-26", "Mar-25", "Cost Mar", "Mar", "MAR")),
			CostApr:         parseDecimal(findField(row, "Apr-26", "Apr-25", "Cost Apr", "Apr", "APR")),
			CostMay:         parseDecimal(findField(row, "May-26", "May-25", "Cost May", "May", "MAY")),
			CostJun:         parseDecimal(findField(row, "Jun-26", "Jun-25", "Cost Jun", "Jun", "JUN")),
			FixCost:         parseDecimal(findField(row, "FIX COST", "Fix Cost")),
			DistributedCost: parseDecimal(findField(row, "DISTRIBUTED COST (IDR/UNIT)", "DISTRIBUTED COST", "Distributed Cost")),
			CargoCarried:    parseDecimal(findField(row, "CARGO CARRIED (MT)", "CARGO CARRIED", "Cargo Carried")),
			UnitCost:        parseDecimal(findField(row, "UNIT COST (IDR/MT)", "UNIT COST", "Unit Cost")),
			CostPerKG:       parseDecimal(findField(row, "COST/KG", "Cost/KG", "Cost Per KG")),
			CostPerKGKM:     parseDecimal(findField(row, "COST/KG/KM", "Cost/KG/KM")),
			Notes:           findField(row, "Notes", "Note", "NOTES"),
			ValidityStart:   parseDate(findField(row, "VALIDITY START", "Validity Start", "Start Date", "START", "VALIDITY\nSTART", "Valid Start", "Valid From", "Validty Start")),
			ValidityEnd:     parseDate(findField(row, "VALIDITY END", "Validity End", "End Date", "END", "VALIDITY\nEND", "Valid End", "Valid Until", "Validty End", "Expiry", "Expiration", "To Date", "Until")),
		}
		contracts = append(contracts, c)
	}

	if len(contracts) > 0 {
		if err := s.contractRepo.BulkCreateDedicatedFix(contracts); err != nil {
			errs = append(errs, fmt.Sprintf("Bulk insert dedicated_fix failed: %v", err))
			return 0, errs
		}
	}

	return len(contracts), errs
}

func (s *ImportService) importDedicatedVar(sheet ParsedSheet) (int, []string) {
	var contracts []models.ContractDedicatedVar
	var errs []string

	for i, row := range sheet.Rows {
		if isEmptyRow(row) {
			continue
		}
		vendorID, err := s.resolveVendor(row)
		if err != nil {
			if err.Error() == "vendor name is empty" {
				continue
			}
			errs = append(errs, fmt.Sprintf("Sheet '%s' row %d: %v", sheet.SheetName, i+2, err))
			continue
		}
		millID, err := s.resolveMill(row)
		if err != nil {
			if err.Error() == "mill name is empty" {
				continue
			}
			errs = append(errs, fmt.Sprintf("Sheet '%s' row %d: %v", sheet.SheetName, i+2, err))
			continue
		}

		originZoneID, _ := s.resolveZone(row, "ORIGIN ZONE", "Origin Zone", "Origin")
		destZoneID, _ := s.resolveZone(row, "DESTINATION ZONE", "Destination Zone", "Dest Zone", "Dest")
		motID, _ := s.resolveMot(row)
		uomID, _ := s.resolveUom(row)

		c := models.ContractDedicatedVar{
			VendorID:      vendorID,
			MillID:        millID,
			AreaCategory:  findField(row, "AREA/CATEGORY", "Area/Category", "Area"),
			ProposalCFAS:  findField(row, "PROPOSAL/CFAS", "Proposal/CFAS", "Proposal", "CFAS"),
			FANumber:      findField(row, "FA NUMBER", "FA Number", "FA No"),
			OriginZoneID:  originZoneID,
			DestZoneID:    destZoneID,
			MotID:         motID,
			UomID:         uomID,
			Distance:      parseDecimal(findField(row, "DISTANCE (KM)", "Distance")),
			SPKNumber:     findField(row, "SPK NUMBER", "SPK Number", "SPK"),
			ValidityStart: parseDate(findField(row, "VALIDITY START", "Validity Start", "Start Date", "START", "VALIDITY\nSTART", "Valid Start", "Valid From", "Validty Start")),
			ValidityEnd:   parseDate(findField(row, "VALIDITY END", "Validity End", "End Date", "END", "VALIDITY\nEND", "Valid End", "Valid Until", "Validty End", "Expiry", "Expiration", "To Date", "Until")),
			Payload:       parseDecimal(findField(row, "PAYLOAD", "Payload")),
			CostIDR:       parseDecimal(findField(row, "COST (IDR)", "Cost (IDR)", "CostIDR")),
			CostPerKG:     parseDecimal(findField(row, "COST/KG", "Cost/KG")),
			CostPerKGKM:   parseDecimal(findField(row, "COST/KG/KM", "Cost/KG/KM")),
			Notes:         findField(row, "Notes", "Note", "NOTES"),
		}
		contracts = append(contracts, c)
	}

	if len(contracts) > 0 {
		if err := s.contractRepo.BulkCreateDedicatedVar(contracts); err != nil {
			errs = append(errs, fmt.Sprintf("Bulk insert dedicated_var failed: %v", err))
			return 0, errs
		}
	}

	return len(contracts), errs
}

func (s *ImportService) importOncall(sheet ParsedSheet) (int, []string) {
	var contracts []models.ContractOncall
	var errs []string

	for i, row := range sheet.Rows {
		if isEmptyRow(row) {
			continue
		}
		vendorID, err := s.resolveVendor(row)
		if err != nil {
			if err.Error() == "vendor name is empty" {
				continue
			}
			errs = append(errs, fmt.Sprintf("Sheet '%s' row %d: %v", sheet.SheetName, i+2, err))
			continue
		}
		millID, err := s.resolveMill(row)
		if err != nil {
			if err.Error() == "mill name is empty" {
				continue
			}
			errs = append(errs, fmt.Sprintf("Sheet '%s' row %d: %v", sheet.SheetName, i+2, err))
			continue
		}

		productID, _ := s.resolveProduct(row)
		originZoneID, _ := s.resolveZone(row, "ORIGIN ZONE", "Origin Zone", "Origin")
		destZoneID, _ := s.resolveZone(row, "DESTINATION ZONE", "Destination Zone", "Dest Zone")
		motID, _ := s.resolveMot(row)
		uomID, _ := s.resolveUom(row)

		c := models.ContractOncall{
			VendorID:       vendorID,
			MillID:         millID,
			ProductID:      productID,
			AreaCategory:   findField(row, "AREA/CATEGORY", "Area/Category", "Area"),
			ProposalCFAS:   findField(row, "PROPOSAL/CFAS", "Proposal/CFAS", "Proposal", "CFAS"),
			FANumber:       findField(row, "FA NUMBER", "FA Number"),
			OriginZoneID:   originZoneID,
			DestZoneID:     destZoneID,
			MotID:          motID,
			UomID:          uomID,
			SPKNumber:      findField(row, "SPK NUMBER", "SPK Number", "SPK"),
			ValidityStart:  parseDate(findField(row, "VALIDITY START", "Validity Start", "Start Date", "START", "VALIDITY\nSTART", "Valid Start", "Valid From", "Validty Start")),
			ValidityEnd:    parseDate(findField(row, "VALIDITY END", "Validity End", "End Date", "END", "VALIDITY\nEND", "Valid End", "Valid Until", "Validty End", "Expiry", "Expiration", "To Date", "Until")),
			Payload:        parseDecimal(findField(row, "PAYLOAD", "Payload")),
			CostIDR:        parseDecimal(findField(row, "COST (IDR)", "Cost (IDR)")),
			CostPerKG:      parseDecimal(findField(row, "COST/KG", "Cost/KG")),
			CostPerTon:     parseDecimal(findField(row, "COST/TON", "Cost/Ton")),
			Distance:       parseDecimal(findField(row, "DISTANCE (KM)", "Distance")),
			LoadingCost:    parseDecimal(findField(row, "LOADING COST (IDR)", "Loading Cost", "Loading", "LOADING")),
			UnloadingCost:  parseDecimal(findField(row, "UNLOADING COST (IDR)", "Unloading Cost", "Unloading", "UNLOADING")),
			RunningCostIDR: parseDecimal(findField(row, "RUNNING COST (IDR/TON/KM)", "Running Cost", "Running Cost IDR", "IDR/Ton/KM")),
			RunningCostUSD: parseDecimal(findField(row, "RUNNING COST (USD/TON/KM)", "Running Cost USD")),
			Notes:          findField(row, "NOTES", "Notes", "Note"),
		}
		contracts = append(contracts, c)
	}

	if len(contracts) > 0 {
		if err := s.contractRepo.BulkCreateOncall(contracts); err != nil {
			errs = append(errs, fmt.Sprintf("Bulk insert oncall failed: %v", err))
			return 0, errs
		}
	}

	return len(contracts), errs
}

// --- Helper functions ---

// isEmptyRow checks if all fields in a row are effectively empty
func isEmptyRow(row map[string]string) bool {
	for _, val := range row {
		if strings.TrimSpace(val) != "" {
			return false
		}
	}
	return true
}

// findField looks for a value in the row map trying multiple possible header names.
// It handles Excel headers that may contain newline characters (e.g., "VALIDITY\nSTART").
func findField(row map[string]string, names ...string) string {
	normalize := func(s string) string {
		s = strings.ToLower(s)
		s = strings.ReplaceAll(s, "\n", " ")
		s = strings.ReplaceAll(s, "\r", "")
		return strings.Join(strings.Fields(s), " ")
	}

	// Pass 1: exact match
	for _, name := range names {
		if val, ok := row[name]; ok && strings.TrimSpace(val) != "" {
			return strings.TrimSpace(val)
		}
	}

	// Pass 2: normalized match
	for _, name := range names {
		normName := normalize(name)
		for key, val := range row {
			if normalize(key) == normName && strings.TrimSpace(val) != "" {
				return strings.TrimSpace(val)
			}
		}
	}

	// Pass 3: contains match for validity specially
	for _, name := range names {
		if strings.Contains(strings.ToLower(name), "valid") {
			lowerName := strings.ToLower(name)
			for key, val := range row {
				lowerKey := strings.ToLower(key)
				if strings.Contains(lowerKey, "valid") && strings.TrimSpace(val) != "" {
					// Check if searching for start or end
					if strings.Contains(lowerName, "start") && (strings.Contains(lowerKey, "start") || strings.Contains(lowerKey, "from")) {
						return strings.TrimSpace(val)
					}
					if (strings.Contains(lowerName, "end") || strings.Contains(lowerName, "until")) && (strings.Contains(lowerKey, "end") || strings.Contains(lowerKey, "until") || strings.Contains(lowerKey, "to")) {
						return strings.TrimSpace(val)
					}
				}
			}
		}
	}

	return ""
}

// parseDecimal converts a string to a decimal, handling common number formats.
func parseDecimal(s string) decimal.Decimal {
	if s == "" {
		return decimal.Zero
	}
	// Remove thousand separators and whitespace
	cleaned := strings.ReplaceAll(s, ",", "")
	cleaned = strings.ReplaceAll(cleaned, " ", "")
	// Try to parse as float first for scientific notation
	if val, err := strconv.ParseFloat(cleaned, 64); err == nil {
		return decimal.NewFromFloat(val)
	}
	d, err := decimal.NewFromString(cleaned)
	if err != nil {
		return decimal.Zero
	}
	return d
}

// parseDate tries multiple date formats.
func parseDate(s string) *time.Time {
	if s == "" {
		return nil
	}
	// Support common Excel date formats
	formats := []string{
		"2006-01-02",
		"02/01/2006",
		"01/02/2006",
		"2006/01/02",
		"02-Jan-2006",
		"2-Jan-2006",
		"02-Jan-06",
		"2-Jan-06",
		"02-Jan-2006",
		"2-Jan-2006",
		"Jan-06", // MMM-YY
		"Jan-2006",
		"January 2006",
		"02.01.2006",
		"01.02.2006",
		"2 January 2006",
		"January 2, 2006",
		time.RFC3339,
	}
	cleaned := strings.TrimSpace(s)
	// Try parsing with each format
	for _, layout := range formats {
		if t, err := time.Parse(layout, cleaned); err == nil {
			// If it's a month-only format like Jan-06, we might want to adjust it,
			// but for now let's just return the 1st of that month.
			return &t
		}
	}

	// Try common Indonesian or mixed formats
	cleanedLower := strings.ToLower(cleaned)
	if strings.Contains(cleanedLower, "jan") { cleaned = strings.Replace(cleanedLower, "jan", "Jan", 1) }
	// ... could add more but let's stick to standard English for now as Go's time.Parse expects English

	// Try to handle Excel serial numbers (e.g. 45291)
	if f, err := strconv.ParseFloat(cleaned, 64); err == nil && f > 20000 {
		// Excel date epoch is 1899-12-30
		excelEpoch := time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)
		t := excelEpoch.Add(time.Duration(f * float64(24*time.Hour)))
		return &t
	}

	return nil
}
