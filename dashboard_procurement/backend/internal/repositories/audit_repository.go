package repositories

import (
	"rygell-dashboard/internal/models"

	"gorm.io/gorm"
)

// AuditRepository handles audit log operations.
type AuditRepository struct {
	db *gorm.DB
}

// NewAuditRepository creates a new AuditRepository.
func NewAuditRepository(db *gorm.DB) *AuditRepository {
	return &AuditRepository{db: db}
}

// Create inserts a new audit log entry.
func (r *AuditRepository) Create(log *models.AuditLog) error {
	return r.db.Create(log).Error
}

// GetByEntity returns all audit logs for a specific entity.
func (r *AuditRepository) GetByEntity(entityType string, entityID uint) ([]models.AuditLog, error) {
	var logs []models.AuditLog
	err := r.db.Where("entity_type = ? AND entity_id = ?", entityType, entityID).
		Order("created_at DESC").
		Find(&logs).Error
	return logs, err
}

// GetLatestByEntity returns the most recent audit log for a specific entity.
func (r *AuditRepository) GetLatestByEntity(entityType string, entityID uint) (*models.AuditLog, error) {
	var log models.AuditLog
	err := r.db.Where("entity_type = ? AND entity_id = ?", entityType, entityID).
		Order("created_at DESC").
		First(&log).Error
	return &log, err
}

// GetAll returns all audit logs ordered by most recent.
func (r *AuditRepository) GetAll(limit int) ([]models.AuditLog, error) {
	var logs []models.AuditLog
	query := r.db.Order("created_at DESC")
	if limit > 0 {
		query = query.Limit(limit)
	}
	err := query.Find(&logs).Error
	return logs, err
}
// GetByVendor returns all audit logs for a specific vendor, including those from their contracts.
func (r *AuditRepository) GetByVendor(vendorID uint) ([]models.AuditLog, error) {
	var logs []models.AuditLog
	
	// Complex query: logs for the vendor itself OR logs for any of the vendor's contracts
	err := r.db.Raw(`
		SELECT * FROM audit_logs 
		WHERE (entity_type = 'vendor' AND entity_id = ?)
		OR (entity_type = 'contract_dedicated_fix' AND entity_id IN (SELECT id FROM contract_dedicated_fixes WHERE vendor_id = ?))
		OR (entity_type = 'contract_dedicated_var' AND entity_id IN (SELECT id FROM contract_dedicated_vars WHERE vendor_id = ?))
		OR (entity_type = 'contract_oncall' AND entity_id IN (SELECT id FROM contract_oncalls WHERE vendor_id = ?))
		ORDER BY created_at DESC
	`, vendorID, vendorID, vendorID, vendorID).Scan(&logs).Error
	
	return logs, err
}
