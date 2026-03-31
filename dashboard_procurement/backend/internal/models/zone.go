package models

import (
	"time"

	"gorm.io/gorm"
)

// Zone represents an origin or destination zone.
type Zone struct {
	ID        uint           `gorm:"primaryKey" json:"id"`
	Name      string         `gorm:"size:255;not null" json:"name"`
	Type      string         `gorm:"size:50;not null" json:"type"` // "origin" or "destination"
	CreatedAt time.Time      `json:"created_at"`
	UpdatedAt time.Time      `json:"updated_at"`
	DeletedAt gorm.DeletedAt `gorm:"index" json:"deleted_at,omitempty"`
}
