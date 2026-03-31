package router

import (
	"rygell-dashboard/internal/config"
	"rygell-dashboard/internal/handlers"
	"rygell-dashboard/internal/middleware"
	"rygell-dashboard/internal/repositories"
	"rygell-dashboard/internal/services"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// Setup initializes all dependencies and registers routes.
func Setup(db *gorm.DB, cfg *config.Config) *gin.Engine {
	r := gin.Default()

	// Middleware
	r.Use(middleware.CORSMiddleware())

	// --- Initialize layers ---

	// Repositories
	masterRepo := repositories.NewMasterRepository(db)
	contractRepo := repositories.NewContractRepository(db)
	auditRepo := repositories.NewAuditRepository(db)
	userRepo := repositories.NewUserRepository(db)

	// Services
	masterService := services.NewMasterService(masterRepo)
	contractService := services.NewContractService(contractRepo, auditRepo)
	parserService := services.NewParserService()
	exportService := services.NewExportService(contractRepo, masterRepo)
	userService := services.NewUserService(userRepo, cfg.JWTSecret, cfg.JWTExpiryHours)

	importService := services.NewImportService(parserService, masterRepo, contractRepo)

	// Handlers
	masterHandler := handlers.NewMasterHandler(masterService)
	contractHandler := handlers.NewContractHandler(contractService)
	importHandler := handlers.NewImportHandler(parserService, importService, cfg)
	exportHandler := handlers.NewExportHandler(exportService)
	authHandler := handlers.NewAuthHandler(userService)

	// --- Register Routes ---
	api := r.Group("/api/v1")

	// Health check
	api.GET("/health", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok"})
	})
	api.POST("/auth/login", authHandler.Login)

	protected := api.Group("")
	protected.Use(middleware.AuthMiddleware(cfg.JWTSecret))
	protected.GET("/auth/me", authHandler.Me)

	// Master Data
	mills := protected.Group("/mills")
	{
		mills.GET("", masterHandler.GetAllMills)
		mills.GET("/:id", masterHandler.GetMillByID)
		mills.POST("", masterHandler.CreateMill)
		mills.PUT("/:id", masterHandler.UpdateMill)
		mills.DELETE("/:id", masterHandler.DeleteMill)
	}

	vendors := protected.Group("/vendors")
	{
		vendors.GET("", masterHandler.GetAllVendors)
		vendors.GET("/:id", masterHandler.GetVendorByID)
		vendors.POST("", masterHandler.CreateVendor)
		vendors.PUT("/:id", masterHandler.UpdateVendor)
		vendors.DELETE("/:id", masterHandler.DeleteVendor)
	}

	products := protected.Group("/products")
	{
		products.GET("", masterHandler.GetAllProducts)
		products.GET("/:id", masterHandler.GetProductByID)
		products.POST("", masterHandler.CreateProduct)
		products.PUT("/:id", masterHandler.UpdateProduct)
		products.DELETE("/:id", masterHandler.DeleteProduct)
	}

	zones := protected.Group("/zones")
	{
		zones.GET("", masterHandler.GetAllZones)
		zones.GET("/:id", masterHandler.GetZoneByID)
		zones.POST("", masterHandler.CreateZone)
		zones.PUT("/:id", masterHandler.UpdateZone)
		zones.DELETE("/:id", masterHandler.DeleteZone)
	}

	mots := protected.Group("/mots")
	{
		mots.GET("", masterHandler.GetAllMots)
		mots.GET("/:id", masterHandler.GetMotByID)
		mots.POST("", masterHandler.CreateMot)
		mots.PUT("/:id", masterHandler.UpdateMot)
		mots.DELETE("/:id", masterHandler.DeleteMot)
	}

	uoms := protected.Group("/uoms")
	{
		uoms.GET("", masterHandler.GetAllUoms)
		uoms.GET("/:id", masterHandler.GetUomByID)
		uoms.POST("", masterHandler.CreateUom)
		uoms.PUT("/:id", masterHandler.UpdateUom)
		uoms.DELETE("/:id", masterHandler.DeleteUom)
	}

	// Contracts
	dedicatedFix := protected.Group("/contracts/dedicated-fix")
	{
		dedicatedFix.GET("", contractHandler.GetAllDedicatedFix)
		dedicatedFix.GET("/:id", contractHandler.GetDedicatedFixByID)
		dedicatedFix.POST("", contractHandler.CreateDedicatedFix)
		dedicatedFix.PUT("/:id", contractHandler.UpdateDedicatedFix)
		dedicatedFix.PATCH("/:id", contractHandler.UpdateDedicatedFix)
		dedicatedFix.DELETE("/:id", contractHandler.DeleteDedicatedFix)
		dedicatedFix.PATCH("/:id/agreement", contractHandler.UpdateDedicatedFixAgreement)
	}

	dedicatedVar := protected.Group("/contracts/dedicated-var")
	{
		dedicatedVar.GET("", contractHandler.GetAllDedicatedVar)
		dedicatedVar.GET("/:id", contractHandler.GetDedicatedVarByID)
		dedicatedVar.POST("", contractHandler.CreateDedicatedVar)
		dedicatedVar.PUT("/:id", contractHandler.UpdateDedicatedVar)
		dedicatedVar.PATCH("/:id", contractHandler.UpdateDedicatedVar)
		dedicatedVar.DELETE("/:id", contractHandler.DeleteDedicatedVar)
	}

	oncall := protected.Group("/contracts/oncall")
	{
		oncall.GET("", contractHandler.GetAllOncall)
		oncall.GET("/:id", contractHandler.GetOncallByID)
		oncall.POST("", contractHandler.CreateOncall)
		oncall.PUT("/:id", contractHandler.UpdateOncall)
		oncall.PATCH("/:id", contractHandler.UpdateOncall)
		oncall.DELETE("/:id", contractHandler.DeleteOncall)
	}

	// Audit
	protected.GET("/audit/:entity_type/:entity_id", contractHandler.GetAuditHistory)
	protected.GET("/audit/vendor/:id", contractHandler.GetVendorAuditHistory)
	protected.PATCH("/vendors/:id/agreement", contractHandler.UpdateVendorAgreement)
	protected.PATCH("/mills/:id/agreement", contractHandler.UpdateMillAgreement)

	// Import / Export
	protected.POST("/import/excel", importHandler.UploadAndParse)
	protected.POST("/import/confirm", importHandler.ConfirmImport)
	protected.GET("/export/dedicated-fix", exportHandler.ExportDedicatedFix)
	protected.GET("/export/dedicated-var", exportHandler.ExportDedicatedVar)
	protected.GET("/export/oncall", exportHandler.ExportOncall)

	return r
}
