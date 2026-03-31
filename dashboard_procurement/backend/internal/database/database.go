package database

import (
	"fmt"

	"rygell-dashboard/internal/config"
	"rygell-dashboard/internal/models"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// Connect establishes a connection to the PostgreSQL database.
func Connect(cfg *config.Config) (*gorm.DB, error) {
	dsn := fmt.Sprintf(
		"host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		cfg.DBHost, cfg.DBPort, cfg.DBUser, cfg.DBPassword, cfg.DBName,
	)

	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Info),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	return db, nil
}

// Migrate runs auto-migration for all models.
func Migrate(db *gorm.DB) error {
	return db.AutoMigrate(
		&models.Mill{},
		&models.Vendor{},
		&models.Product{},
		&models.Zone{},
		&models.Mot{},
		&models.Uom{},
		&models.ContractDedicatedFix{},
		&models.ContractDedicatedVar{},
		&models.ContractOncall{},
		&models.AuditLog{},
		&models.User{},
	)
}
