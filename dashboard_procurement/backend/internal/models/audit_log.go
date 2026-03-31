package models

import "time"

// AuditLog stores the history of agreement updates.
type AuditLog struct {
	ID           uint   `gorm:"primaryKey" json:"id"`
	EntityType   string `gorm:"size:100;not null;index" json:"entity_type"`   // e.g. "contract_dedicated_fix"
	EntityID     uint   `gorm:"not null;index" json:"entity_id"`              // ID of the related record
	Action       string `gorm:"size:50;not null" json:"action"`               // "create", "update", "agreement_update"
	ChangedBy    string `gorm:"size:255" json:"changed_by"`                   // Name/identifier of the person
	AgreementNote string `gorm:"type:text" json:"agreement_note"`             // Latest agreement/negotiation notes
	OldData      string `gorm:"type:jsonb" json:"old_data,omitempty"`         // Snapshot of previous data as JSON
	NewData      string `gorm:"type:jsonb" json:"new_data,omitempty"`         // Snapshot of new data as JSON
	CreatedAt    time.Time `json:"created_at"`
}
