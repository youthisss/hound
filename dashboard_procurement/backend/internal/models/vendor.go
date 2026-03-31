package models

import (
	"time"

	"gorm.io/gorm"
)

// Vendor represents a logistics/supply vendor.
type Vendor struct {
	ID        uint           `gorm:"primaryKey" json:"id"`
	Code      string         `gorm:"uniqueIndex;size:50;not null" json:"code"`
	Name      string         `gorm:"size:255;not null" json:"name"`
	TaxID     string         `gorm:"size:50" json:"tax_id"`
	Status    string         `gorm:"size:50;default:'active'" json:"status"`
	Address   string         `gorm:"type:text" json:"address"`
	ContactPerson string     `gorm:"size:255" json:"contact_person"`
	Email     string         `gorm:"size:255" json:"email"`
	Phone     string         `gorm:"size:50" json:"phone"`
	CreatedAt time.Time      `json:"created_at"`
	UpdatedAt time.Time      `json:"updated_at"`
	DeletedAt gorm.DeletedAt `gorm:"index" json:"deleted_at,omitempty"`
}
