package models

import (
	"time"

	"github.com/shopspring/decimal"
	"gorm.io/gorm"
)

// ContractDedicatedFix stores monthly cost data for dedicated fixed contracts.
type ContractDedicatedFix struct {
	ID              uint            `gorm:"primaryKey" json:"id"`
	MillID          uint            `gorm:"index;not null" json:"mill_id"`
	Mill            Mill            `gorm:"foreignKey:MillID" json:"mill,omitempty"`
	VendorID        uint            `gorm:"index;not null" json:"vendor_id"`
	Vendor          Vendor          `gorm:"foreignKey:VendorID" json:"vendor,omitempty"`
	ProductID       *uint           `gorm:"index" json:"product_id,omitempty"`
	Product         *Product        `gorm:"foreignKey:ProductID" json:"product,omitempty"`
	LicensePlate    string          `gorm:"size:50" json:"license_plate"`
	SPKNumber       string          `gorm:"size:100;index" json:"spk_number"`
	AreaCategory    string          `gorm:"size:100" json:"area_category,omitempty"`
	ProposalCFAS    string          `gorm:"size:100" json:"proposal_cfas,omitempty"`
	FANumber        string          `gorm:"size:100" json:"fa_number,omitempty"`
	MotID           *uint           `gorm:"index" json:"mot_id,omitempty"`
	Mot             *Mot            `gorm:"foreignKey:MotID" json:"mot,omitempty"`
	UomID           *uint           `gorm:"index" json:"uom_id,omitempty"`
	Uom             *Uom            `gorm:"foreignKey:UomID" json:"uom,omitempty"`
	ValidityStart   *time.Time      `json:"validity_start,omitempty"`
	ValidityEnd     *time.Time      `json:"validity_end,omitempty"`
	CostJan         decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cost_jan"`
	CostFeb         decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cost_feb"`
	CostMar         decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cost_mar"`
	CostApr         decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cost_apr"`
	CostMay         decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cost_may"`
	CostJun         decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cost_jun"`
	FixCost         decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"fix_cost"`
	CargoCarried    decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"cargo_carried"`
	UnitCost        decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"unit_cost"`
	CostPerKG       decimal.Decimal `gorm:"type:numeric(15,4);default:0" json:"cost_per_kg"`
	CostPerKGKM     decimal.Decimal `gorm:"type:numeric(15,4);default:0" json:"cost_per_kg_km"`
	DistributedCost decimal.Decimal `gorm:"type:numeric(15,2);default:0" json:"distributed_cost"`
	Notes           string          `gorm:"type:text" json:"notes"`
	CreatedAt       time.Time       `json:"created_at"`
	UpdatedAt       time.Time       `json:"updated_at"`
	DeletedAt       gorm.DeletedAt  `gorm:"index" json:"deleted_at,omitempty"`
}
