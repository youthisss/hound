package services

import (
	"encoding/json"
	"strconv"

	"rygell-dashboard/internal/models"
	"rygell-dashboard/internal/repositories"
)

// ContractService handles business logic for contracts and audit logging.
type ContractService struct {
	contractRepo *repositories.ContractRepository
	auditRepo    *repositories.AuditRepository
}

// NewContractService creates a new ContractService.
func NewContractService(contractRepo *repositories.ContractRepository, auditRepo *repositories.AuditRepository) *ContractService {
	return &ContractService{
		contractRepo: contractRepo,
		auditRepo:    auditRepo,
	}
}

// --- Dedicated Fix ---

func (s *ContractService) GetAllDedicatedFix(filters map[string]interface{}, search string) ([]models.ContractDedicatedFix, error) {
	return s.contractRepo.GetAllDedicatedFix(filters, search)
}

func (s *ContractService) GetDedicatedFixByID(id uint) (*models.ContractDedicatedFix, error) {
	return s.contractRepo.GetDedicatedFixByID(id)
}

func (s *ContractService) CreateDedicatedFix(contract *models.ContractDedicatedFix) error {
	if err := s.contractRepo.CreateDedicatedFix(contract); err != nil {
		return err
	}
	s.logAudit("contract_dedicated_fix", contract.ID, "create", "", "", contract)
	return nil
}

func (s *ContractService) UpdateDedicatedFix(contract *models.ContractDedicatedFix, changedBy, note string) error {
	old, _ := s.contractRepo.GetDedicatedFixByID(contract.ID)
	if err := s.contractRepo.UpdateDedicatedFix(contract); err != nil {
		return err
	}
	s.logAudit("contract_dedicated_fix", contract.ID, "update", changedBy, note, old)
	return nil
}

func (s *ContractService) DeleteDedicatedFix(id uint) error {
	return s.contractRepo.DeleteDedicatedFix(id)
}

// UpdateDedicatedFixAgreement updates only the agreement note on a contract.
func (s *ContractService) UpdateDedicatedFixAgreement(id uint, changedBy, note string) error {
	contract, err := s.contractRepo.GetDedicatedFixByID(id)
	if err != nil {
		return err
	}
	contract.Notes = note
	if err := s.contractRepo.UpdateDedicatedFix(contract); err != nil {
		return err
	}
	s.logAudit("contract_dedicated_fix", id, "agreement_update", changedBy, note, nil)
	return nil
}

// --- Dedicated Var ---

func (s *ContractService) GetAllDedicatedVar(filters map[string]interface{}, search string) ([]models.ContractDedicatedVar, error) {
	return s.contractRepo.GetAllDedicatedVar(filters, search)
}

func (s *ContractService) GetDedicatedVarByID(id uint) (*models.ContractDedicatedVar, error) {
	return s.contractRepo.GetDedicatedVarByID(id)
}

func (s *ContractService) CreateDedicatedVar(contract *models.ContractDedicatedVar) error {
	if err := s.contractRepo.CreateDedicatedVar(contract); err != nil {
		return err
	}
	s.logAudit("contract_dedicated_var", contract.ID, "create", "", "", contract)
	return nil
}

func (s *ContractService) UpdateDedicatedVar(contract *models.ContractDedicatedVar, changedBy, note string) error {
	old, _ := s.contractRepo.GetDedicatedVarByID(contract.ID)
	if err := s.contractRepo.UpdateDedicatedVar(contract); err != nil {
		return err
	}
	s.logAudit("contract_dedicated_var", contract.ID, "update", changedBy, note, old)
	return nil
}

func (s *ContractService) DeleteDedicatedVar(id uint) error {
	return s.contractRepo.DeleteDedicatedVar(id)
}

// UpdateDedicatedVarAgreement updates only the agreement note on a var contract.
func (s *ContractService) UpdateDedicatedVarAgreement(id uint, changedBy, note string) error {
	contract, err := s.contractRepo.GetDedicatedVarByID(id)
	if err != nil {
		return err
	}
	contract.Notes = note
	if err := s.contractRepo.UpdateDedicatedVar(contract); err != nil {
		return err
	}
	s.logAudit("contract_dedicated_var", id, "agreement_update", changedBy, note, nil)
	return nil
}

// --- Oncall ---

func (s *ContractService) GetAllOncall(filters map[string]interface{}, search string) ([]models.ContractOncall, error) {
	return s.contractRepo.GetAllOncall(filters, search)
}

func (s *ContractService) GetOncallByID(id uint) (*models.ContractOncall, error) {
	return s.contractRepo.GetOncallByID(id)
}

func (s *ContractService) CreateOncall(contract *models.ContractOncall) error {
	if err := s.contractRepo.CreateOncall(contract); err != nil {
		return err
	}
	s.logAudit("contract_oncall", contract.ID, "create", "", "", contract)
	return nil
}

func (s *ContractService) UpdateOncall(contract *models.ContractOncall, changedBy, note string) error {
	old, _ := s.contractRepo.GetOncallByID(contract.ID)
	if err := s.contractRepo.UpdateOncall(contract); err != nil {
		return err
	}
	s.logAudit("contract_oncall", contract.ID, "update", changedBy, note, old)
	return nil
}

func (s *ContractService) DeleteOncall(id uint) error {
	return s.contractRepo.DeleteOncall(id)
}

// UpdateOncallAgreement updates only the agreement note on an oncall contract.
func (s *ContractService) UpdateOncallAgreement(id uint, changedBy, note string) error {
	contract, err := s.contractRepo.GetOncallByID(id)
	if err != nil {
		return err
	}
	contract.Notes = note
	if err := s.contractRepo.UpdateOncall(contract); err != nil {
		return err
	}
	s.logAudit("contract_oncall", id, "agreement_update", changedBy, note, nil)
	return nil
}

// --- Map-based Updates (partial update, no association conflicts) ---

// sanitizeUpdateMap removes nested objects and metadata fields from the update map
// so GORM only updates scalar columns.
func sanitizeUpdateMap(body map[string]interface{}) map[string]interface{} {
	// Keys to delete: nested objects and metadata
	deleteKeys := []string{
		"mill", "vendor", "product", "mot", "uom",
		"origin_zone", "dest_zone", "created_at", "updated_at", "deleted_at", "id",
	}
	for _, k := range deleteKeys {
		delete(body, k)
	}

	// Convert string numeric values to float64 for decimal columns
	numericKeys := []string{
		"distance", "payload", "loading_cost", "unloading_cost",
		"cost_idr", "cost_per_kg", "cost_per_ton", "cost_per_kg_km",
		"running_cost_idr", "running_cost_usd",
		"cost_jan", "cost_feb", "cost_mar", "cost_apr", "cost_may", "cost_jun",
		"fix_cost", "distributed_cost", "cargo_carried", "unit_cost",
	}
	for _, k := range numericKeys {
		if v, ok := body[k]; ok {
			switch val := v.(type) {
			case string:
				if val == "" {
					body[k] = 0
				} else {
					parsed, err := strconv.ParseFloat(val, 64)
					if err == nil {
						body[k] = parsed
					} else {
						body[k] = 0
					}
				}
			}
		}
	}
	return body
}

func (s *ContractService) UpdateDedicatedFixMap(id uint, body map[string]interface{}, changedBy, note string) (*models.ContractDedicatedFix, error) {
	old, _ := s.contractRepo.GetDedicatedFixByID(id)
	updates := sanitizeUpdateMap(body)
	if err := s.contractRepo.UpdateDedicatedFixMap(id, updates); err != nil {
		return nil, err
	}
	s.logAudit("contract_dedicated_fix", id, "update", changedBy, note, old)
	result, _ := s.contractRepo.GetDedicatedFixByID(id)
	return result, nil
}

func (s *ContractService) UpdateDedicatedVarMap(id uint, body map[string]interface{}, changedBy, note string) (*models.ContractDedicatedVar, error) {
	old, _ := s.contractRepo.GetDedicatedVarByID(id)
	updates := sanitizeUpdateMap(body)
	if err := s.contractRepo.UpdateDedicatedVarMap(id, updates); err != nil {
		return nil, err
	}
	s.logAudit("contract_dedicated_var", id, "update", changedBy, note, old)
	result, _ := s.contractRepo.GetDedicatedVarByID(id)
	return result, nil
}

func (s *ContractService) UpdateOncallMap(id uint, body map[string]interface{}, changedBy, note string) (*models.ContractOncall, error) {
	old, _ := s.contractRepo.GetOncallByID(id)
	updates := sanitizeUpdateMap(body)
	if err := s.contractRepo.UpdateOncallMap(id, updates); err != nil {
		return nil, err
	}
	s.logAudit("contract_oncall", id, "update", changedBy, note, old)
	result, _ := s.contractRepo.GetOncallByID(id)
	return result, nil
}

// --- Audit History ---

func (s *ContractService) GetAuditHistory(entityType string, entityID uint) ([]models.AuditLog, error) {
	return s.auditRepo.GetByEntity(entityType, entityID)
}

func (s *ContractService) GetVendorAuditHistory(vendorID uint) ([]models.AuditLog, error) {
	return s.auditRepo.GetByVendor(vendorID)
}

// UpdateVendorAgreement adds a negotiation note directly to a vendor.
func (s *ContractService) UpdateVendorAgreement(vendorID uint, changedBy, note string) error {
	s.logAudit("vendor", vendorID, "agreement_update", changedBy, note, nil)
	return nil
}

// UpdateMillAgreement adds a negotiation note directly to a mill.
func (s *ContractService) UpdateMillAgreement(millID uint, changedBy, note string) error {
	s.logAudit("mill", millID, "agreement_update", changedBy, note, nil)
	return nil
}

// --- Internal Helpers ---

func (s *ContractService) logAudit(entityType string, entityID uint, action, changedBy, note string, oldData interface{}) {
	audit := &models.AuditLog{
		EntityType:    entityType,
		EntityID:      entityID,
		Action:        action,
		ChangedBy:     changedBy,
		AgreementNote: note,
	}
	if oldData != nil {
		if data, err := json.Marshal(oldData); err == nil {
			audit.OldData = string(data)
		}
	}
	_ = s.auditRepo.Create(audit)
}
