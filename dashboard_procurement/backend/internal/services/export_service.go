package services

import (
	"fmt"

	"rygell-dashboard/internal/models"
	"rygell-dashboard/internal/repositories"

	"github.com/xuri/excelize/v2"
)

// ExportService generates Excel files matching the original template format.
type ExportService struct {
	contractRepo *repositories.ContractRepository
	masterRepo   *repositories.MasterRepository
}

// NewExportService creates a new ExportService.
func NewExportService(contractRepo *repositories.ContractRepository, masterRepo *repositories.MasterRepository) *ExportService {
	return &ExportService{
		contractRepo: contractRepo,
		masterRepo:   masterRepo,
	}
}

// ExportDedicatedFix generates an Excel file for Dedicated Fix contracts.
func (s *ExportService) ExportDedicatedFix() (*excelize.File, error) {
	contracts, err := s.contractRepo.GetAllDedicatedFix(map[string]interface{}{}, "")
	if err != nil {
		return nil, fmt.Errorf("failed to fetch dedicated fix contracts: %w", err)
	}

	f := excelize.NewFile()
	sheet := "Dedicated Fix"
	f.SetSheetName("Sheet1", sheet)

	// Write headers
	headers := []string{
		"AREA/CATEGORY", "MILL/CATEGORY", "CONTRACT TYPE", "PROPOSAL/CFAS", "SPK NUMBER",
		"FA NUMBER", "VALIDITY START", "VALIDITY END", "VENDOR CODE", "TRANSPORTER/CARRIER",
		"MOT", "LICENSE PLATE", "Jan-26", "Feb-26", "Mar-26", "Apr-26", "May-26", "Jun-26",
		"FIX COST", "UOM", "DISTRIBUTED COST (IDR/UNIT)", "CARGO CARRIED (MT)",
		"UNIT COST (IDR/MT)", "COST/KG", "COST/KG/KM",
	}
	for i, h := range headers {
		cell, _ := excelize.CoordinatesToCellName(i+1, 1)
		f.SetCellValue(sheet, cell, h)
	}

	// Write data rows
	for i, c := range contracts {
		row := i + 2
		s.setCellValue(f, sheet, 1, row, c.AreaCategory)
		s.setCellValue(f, sheet, 2, row, c.Mill.Name)
		s.setCellValue(f, sheet, 3, row, "Dedicated Fix")
		s.setCellValue(f, sheet, 4, row, c.ProposalCFAS)
		s.setCellValue(f, sheet, 5, row, c.SPKNumber)
		s.setCellValue(f, sheet, 6, row, c.FANumber)
		s.setCellTime(f, sheet, 7, row, c.ValidityStart)
		s.setCellTime(f, sheet, 8, row, c.ValidityEnd)
		s.setCellValue(f, sheet, 9, row, c.Vendor.Code)
		s.setCellValue(f, sheet, 10, row, c.Vendor.Name)
		s.setCellMot(f, sheet, 11, row, c.Mot)
		s.setCellValue(f, sheet, 12, row, c.LicensePlate)
		s.setCellDecimal(f, sheet, 13, row, c.CostJan)
		s.setCellDecimal(f, sheet, 14, row, c.CostFeb)
		s.setCellDecimal(f, sheet, 15, row, c.CostMar)
		s.setCellDecimal(f, sheet, 16, row, c.CostApr)
		s.setCellDecimal(f, sheet, 17, row, c.CostMay)
		s.setCellDecimal(f, sheet, 18, row, c.CostJun)
		s.setCellDecimal(f, sheet, 19, row, c.FixCost)
		s.setCellUom(f, sheet, 20, row, c.Uom)
		s.setCellDecimal(f, sheet, 21, row, c.DistributedCost)
		s.setCellDecimal(f, sheet, 22, row, c.CargoCarried)
		s.setCellDecimal(f, sheet, 23, row, c.UnitCost)
		s.setCellDecimal(f, sheet, 24, row, c.CostPerKG)
		s.setCellDecimal(f, sheet, 25, row, c.CostPerKGKM)
	}

	return f, nil
}

// ExportDedicatedVar generates an Excel file for Dedicated Var contracts.
func (s *ExportService) ExportDedicatedVar() (*excelize.File, error) {
	contracts, err := s.contractRepo.GetAllDedicatedVar(map[string]interface{}{}, "")
	if err != nil {
		return nil, fmt.Errorf("failed to fetch dedicated var contracts: %w", err)
	}

	f := excelize.NewFile()
	sheet := "Dedicated Var"
	f.SetSheetName("Sheet1", sheet)

	headers := []string{
		"AREA/CATEGORY", "MILL", "CONTRACT TYPE", "PROPOSAL/CFAS", "SPK NUMBER",
		"FA NUMBER", "VALIDITY START", "VALIDITY END", "VENDOR CODE", "TRANSPORTER/CARRIER",
		"ORIGIN ZONE", "DESTINATION ZONE", "DISTANCE (KM)", "MOT", "PAYLOAD",
		"COST (IDR)", "UOM", "COST/KG", "COST/KG/KM",
	}
	for i, h := range headers {
		cell, _ := excelize.CoordinatesToCellName(i+1, 1)
		f.SetCellValue(sheet, cell, h)
	}

	for i, c := range contracts {
		row := i + 2
		s.setCellValue(f, sheet, 1, row, c.AreaCategory)
		s.setCellValue(f, sheet, 2, row, c.Mill.Name)
		s.setCellValue(f, sheet, 3, row, "Dedicated Var")
		s.setCellValue(f, sheet, 4, row, c.ProposalCFAS)
		s.setCellValue(f, sheet, 5, row, c.SPKNumber)
		s.setCellValue(f, sheet, 6, row, c.FANumber)
		s.setCellTime(f, sheet, 7, row, c.ValidityStart)
		s.setCellTime(f, sheet, 8, row, c.ValidityEnd)
		s.setCellValue(f, sheet, 9, row, c.Vendor.Code)
		s.setCellValue(f, sheet, 10, row, c.Vendor.Name)
		s.setCellZone(f, sheet, 11, row, c.OriginZone)
		s.setCellZone(f, sheet, 12, row, c.DestZone)
		s.setCellDecimal(f, sheet, 13, row, c.Distance)
		s.setCellMot(f, sheet, 14, row, c.Mot)
		s.setCellDecimal(f, sheet, 15, row, c.Payload)
		s.setCellDecimal(f, sheet, 16, row, c.CostIDR)
		s.setCellUom(f, sheet, 17, row, c.Uom)
		s.setCellDecimal(f, sheet, 18, row, c.CostPerKG)
		s.setCellDecimal(f, sheet, 19, row, c.CostPerKGKM)
	}

	return f, nil
}

// ExportOncall generates an Excel file for Oncall contracts.
func (s *ExportService) ExportOncall() (*excelize.File, error) {
	contracts, err := s.contractRepo.GetAllOncall(map[string]interface{}{}, "")
	if err != nil {
		return nil, fmt.Errorf("failed to fetch oncall contracts: %w", err)
	}

	f := excelize.NewFile()
	sheet := "Oncall"
	f.SetSheetName("Sheet1", sheet)

	headers := []string{
		"AREA/CATEGORY", "MILL", "PRODUCT", "CONTRACT TYPE", "PROPOSAL/CFAS",
		"SPK NUMBER", "FA NUMBER", "VALIDITY START", "VALIDITY END", "VENDOR CODE",
		"TRANSPORTER/CARRIER", "ORIGIN ZONE", "DESTINATION ZONE", "MOT", "COST (IDR)",
		"UOM", "PAYLOAD", "COST/KG", "COST/TON", "LOADING COST (IDR)",
		"UNLOADING COST (IDR)", "DISTANCE (KM)", "RUNNING COST (IDR/TON/KM)",
		"RUNNING COST (USD/TON/KM)", "NOTES",
	}
	for i, h := range headers {
		cell, _ := excelize.CoordinatesToCellName(i+1, 1)
		f.SetCellValue(sheet, cell, h)
	}

	for i, c := range contracts {
		row := i + 2
		s.setCellValue(f, sheet, 1, row, c.AreaCategory)
		s.setCellValue(f, sheet, 2, row, c.Mill.Name)
		s.setCellProduct(f, sheet, 3, row, c.Product)
		s.setCellValue(f, sheet, 4, row, "Oncall")
		s.setCellValue(f, sheet, 5, row, c.ProposalCFAS)
		s.setCellValue(f, sheet, 6, row, c.SPKNumber)
		s.setCellValue(f, sheet, 7, row, c.FANumber)
		s.setCellTime(f, sheet, 8, row, c.ValidityStart)
		s.setCellTime(f, sheet, 9, row, c.ValidityEnd)
		s.setCellValue(f, sheet, 10, row, c.Vendor.Code)
		s.setCellValue(f, sheet, 11, row, c.Vendor.Name)
		s.setCellZone(f, sheet, 12, row, c.OriginZone)
		s.setCellZone(f, sheet, 13, row, c.DestZone)
		s.setCellMot(f, sheet, 14, row, c.Mot)
		s.setCellDecimal(f, sheet, 15, row, c.CostIDR)
		s.setCellUom(f, sheet, 16, row, c.Uom)
		s.setCellDecimal(f, sheet, 17, row, c.Payload)
		s.setCellDecimal(f, sheet, 18, row, c.CostPerKG)
		s.setCellDecimal(f, sheet, 19, row, c.CostPerTon)
		s.setCellDecimal(f, sheet, 20, row, c.LoadingCost)
		s.setCellDecimal(f, sheet, 21, row, c.UnloadingCost)
		s.setCellDecimal(f, sheet, 22, row, c.Distance)
		s.setCellDecimal(f, sheet, 23, row, c.RunningCostIDR)
		s.setCellDecimal(f, sheet, 24, row, c.RunningCostUSD)
		s.setCellValue(f, sheet, 25, row, c.Notes)
	}

	return f, nil
}

// --- Helpers ---

func (s *ExportService) setCellValue(f *excelize.File, sheet string, col, row int, value interface{}) {
	cell, _ := excelize.CoordinatesToCellName(col, row)
	f.SetCellValue(sheet, cell, value)
}

func (s *ExportService) setCellDecimal(f *excelize.File, sheet string, col, row int, value interface{ InexactFloat64() float64 }) {
	cell, _ := excelize.CoordinatesToCellName(col, row)
	f.SetCellValue(sheet, cell, value.InexactFloat64())
}

func (s *ExportService) setCellTime(f *excelize.File, sheet string, col, row int, t interface{}) {
	cell, _ := excelize.CoordinatesToCellName(col, row)
	if t == nil {
		f.SetCellValue(sheet, cell, "")
		return
	}
	f.SetCellValue(sheet, cell, fmt.Sprintf("%v", t))
}

func (s *ExportService) setCellProduct(f *excelize.File, sheet string, col, row int, p *models.Product) {
	cell, _ := excelize.CoordinatesToCellName(col, row)
	if p != nil {
		f.SetCellValue(sheet, cell, p.Name)
	} else {
		f.SetCellValue(sheet, cell, "")
	}
}

func (s *ExportService) setCellZone(f *excelize.File, sheet string, col, row int, z *models.Zone) {
	cell, _ := excelize.CoordinatesToCellName(col, row)
	if z != nil {
		f.SetCellValue(sheet, cell, z.Name)
	} else {
		f.SetCellValue(sheet, cell, "")
	}
}

func (s *ExportService) setCellMot(f *excelize.File, sheet string, col, row int, m *models.Mot) {
	cell, _ := excelize.CoordinatesToCellName(col, row)
	if m != nil {
		f.SetCellValue(sheet, cell, m.Name)
	} else {
		f.SetCellValue(sheet, cell, "")
	}
}

func (s *ExportService) setCellUom(f *excelize.File, sheet string, col, row int, u *models.Uom) {
	cell, _ := excelize.CoordinatesToCellName(col, row)
	if u != nil {
		f.SetCellValue(sheet, cell, u.Name)
	} else {
		f.SetCellValue(sheet, cell, "")
	}
}
