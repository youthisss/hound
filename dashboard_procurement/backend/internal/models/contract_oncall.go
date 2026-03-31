package models

import (
	"time"

	"github.com/shopspring/decimal"
	"gorm.io/gorm"
)

// ContractOncall stores on-call/spot contract data with running cost.
type ContractOncall struct {
	ID             uint            `gorm:"primaryKey" json:"id"`
	MillID         uint            `gorm:"index;not null" json:"mill_id"`
	Mill           Mill            `gorm:"foreignKey:MillID" json:"mill,omitempty"`
	VendorID       uint            `gorm:"index;not null" json:"vendor_id"`
	Vendor         Vendor          `gorm:"foreignKey:VendorID" json:"vendor,omitempty"`
	ProductID      *uint           `gorm:"index" json:"product_id,omitempty"`
	Product        *Product        `gorm:"foreignKey:ProductID" json:"product,omitempty"`
	OriginZoneID   *uint           `gorm:"index" json:"origin_zone_id,omitempty"`
	OriginZone     *Zone           `gorm:"foreignKey:OriginZoneID" json:"origin_zone,omitempty"`
	DestZoneID     *uint           `gorm:"index" json:"dest_zone_id,omitempty"`
	DestZone       *Zone           `gorm:"foreignKey:DestZoneID" json:"dest_zone,omitempty"`
	MotID          *uint           `gorm:"index" json:"mot_id,omitempty"`
	Mot            *Mot            `gorm:"foreignKey:MotID" json:"mot,omitempty"`
	UomID          *uint           `gorm:"index" json:"uom_id,omitempty"`
	Uom            *Uom            `gorm:"foreignKey:UomID" json:"uom,omitempty"`
	SPKNumber      string          `gorm:"size:100;index" json:"spk_number"`
	AreaCategory   string          `gorm:"size:100" json:"area_category,omitempty"`
	ProposalCFAS   string          `gorm:"size:100" json:"proposal_cfas,omitempty"`
	FANumber       string          `gorm:"size:100" json:"fa_number,omitempty"`
	ValidityStart  *time.Time      `json:"validity_start,omitempty"`
	ValidityEnd    *time.Time      `json:"validity_end,omitempty"`
	Distance       decimal.Decimal `gorm:"type:numeric(10,2);default:0" json:"distance"`
	Payload        decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"payload"`
	LoadingCost    decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"loading_cost"`
	UnloadingCost  decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"unloading_cost"`
	CostIDR        decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cost_idr"`
	CostPerKG      decimal.Decimal `gorm:"type:numeric(15,4);default:0" json:"cost_per_kg"`
	CostPerTon     decimal.Decimal `gorm:"type:numeric(15,4);default:0" json:"cost_per_ton"`
	RunningCostIDR decimal.Decimal `gorm:"type:numeric(15,4);default:0" json:"running_cost_idr"` // IDR/Ton/KM
	RunningCostUSD decimal.Decimal `gorm:"type:numeric(15,4);default:0" json:"running_cost_usd"`
	Notes          string          `gorm:"type:text" json:"notes"`
	CreatedAt      time.Time       `json:"created_at"`
	UpdatedAt      time.Time       `json:"updated_at"`
	DeletedAt      gorm.DeletedAt  `gorm:"index" json:"deleted_at,omitempty"`
}
