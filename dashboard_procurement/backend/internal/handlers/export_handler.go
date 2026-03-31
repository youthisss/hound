package handlers

import (
	"fmt"
	"net/http"

	"rygell-dashboard/internal/services"

	"github.com/gin-gonic/gin"
)

// ExportHandler handles Excel file generation and download.
type ExportHandler struct {
	exportService *services.ExportService
}

// NewExportHandler creates a new ExportHandler.
func NewExportHandler(exportService *services.ExportService) *ExportHandler {
	return &ExportHandler{exportService: exportService}
}

// ExportDedicatedFix generates and downloads a Dedicated Fix Excel file.
func (h *ExportHandler) ExportDedicatedFix(c *gin.Context) {
	f, err := h.exportService.ExportDedicatedFix()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.Header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=dedicated_fix_export.xlsx"))
	if err := f.Write(c.Writer); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to write excel file"})
	}
}

// ExportDedicatedVar generates and downloads a Dedicated Var Excel file.
func (h *ExportHandler) ExportDedicatedVar(c *gin.Context) {
	f, err := h.exportService.ExportDedicatedVar()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.Header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=dedicated_var_export.xlsx"))
	if err := f.Write(c.Writer); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to write excel file"})
	}
}

// ExportOncall generates and downloads an Oncall Excel file.
func (h *ExportHandler) ExportOncall(c *gin.Context) {
	f, err := h.exportService.ExportOncall()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.Header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	c.Header("Content-Disposition", fmt.Sprintf("attachment; filename=oncall_export.xlsx"))
	if err := f.Write(c.Writer); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to write excel file"})
	}
}
