package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"

	"rygell-dashboard/internal/models"
	"rygell-dashboard/internal/services"

	"github.com/gin-gonic/gin"
)

// ContractHandler handles HTTP requests for contract data.
type ContractHandler struct {
	service *services.ContractService
}

// NewContractHandler creates a new ContractHandler.
func NewContractHandler(service *services.ContractService) *ContractHandler {
	return &ContractHandler{service: service}
}

// --- Dedicated Fix ---

func (h *ContractHandler) GetAllDedicatedFix(c *gin.Context) {
	filters := make(map[string]interface{})
	search := c.Query("q")
	if v := c.Query("vendor_id"); v != "" {
		filters["vendor_id"] = v
	}
	if v := c.Query("mill_id"); v != "" {
		filters["mill_id"] = v
	}

	contracts, err := h.service.GetAllDedicatedFix(filters, search)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	total := len(contracts)
	c.Header("X-Total-Count", fmt.Sprintf("%d", total))
	c.Header("Access-Control-Expose-Headers", "X-Total-Count")

	startStr := c.DefaultQuery("_start", "0")
	endStr := c.DefaultQuery("_end", fmt.Sprintf("%d", total))
	start, _ := strconv.Atoi(startStr)
	end, _ := strconv.Atoi(endStr)
	if start < 0 {
		start = 0
	}
	if end > total {
		end = total
	}
	if start > total {
		start = total
	}
	c.JSON(http.StatusOK, contracts[start:end])
}

func (h *ContractHandler) GetDedicatedFixByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	contract, err := h.service.GetDedicatedFixByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "contract not found"})
		return
	}
	c.JSON(http.StatusOK, contract)
}

func (h *ContractHandler) CreateDedicatedFix(c *gin.Context) {
	var contract models.ContractDedicatedFix
	if err := c.ShouldBindJSON(&contract); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateDedicatedFix(&contract); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, contract)
}

func (h *ContractHandler) UpdateDedicatedFix(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	// Fetch existing record
	contract, err := h.service.GetDedicatedFixByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "contract not found"})
		return
	}
	// Read raw body and unmarshal on top of existing record
	bodyBytes, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "failed to read body"})
		return
	}
	if err := json.Unmarshal(bodyBytes, contract); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	contract.ID = uint(id)
	// Clear associations so GORM doesn't try to update them
	contract.Mill = models.Mill{}
	contract.Vendor = models.Vendor{}
	contract.Product = nil
	contract.Mot = nil
	contract.Uom = nil

	changedBy := c.Query("changed_by")
	note := c.Query("note")

	if err := h.service.UpdateDedicatedFix(contract, changedBy, note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	// Return fresh record with associations
	updated, _ := h.service.GetDedicatedFixByID(uint(id))
	c.JSON(http.StatusOK, updated)
}

func (h *ContractHandler) DeleteDedicatedFix(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteDedicatedFix(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// UpdateDedicatedFixAgreement updates only the agreement note.
func (h *ContractHandler) UpdateDedicatedFixAgreement(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var body struct {
		ChangedBy string `json:"changed_by"`
		Note      string `json:"note"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.UpdateDedicatedFixAgreement(uint(id), body.ChangedBy, body.Note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "agreement updated"})
}

// --- Dedicated Var ---

func (h *ContractHandler) GetAllDedicatedVar(c *gin.Context) {
	filters := make(map[string]interface{})
	search := c.Query("q")
	if v := c.Query("vendor_id"); v != "" {
		filters["vendor_id"] = v
	}
	if v := c.Query("mill_id"); v != "" {
		filters["mill_id"] = v
	}

	contracts, err := h.service.GetAllDedicatedVar(filters, search)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	total := len(contracts)
	c.Header("X-Total-Count", fmt.Sprintf("%d", total))
	c.Header("Access-Control-Expose-Headers", "X-Total-Count")

	startStr := c.DefaultQuery("_start", "0")
	endStr := c.DefaultQuery("_end", fmt.Sprintf("%d", total))
	start, _ := strconv.Atoi(startStr)
	end, _ := strconv.Atoi(endStr)
	if start < 0 {
		start = 0
	}
	if end > total {
		end = total
	}
	if start > total {
		start = total
	}
	c.JSON(http.StatusOK, contracts[start:end])
}

func (h *ContractHandler) GetDedicatedVarByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	contract, err := h.service.GetDedicatedVarByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "contract not found"})
		return
	}
	c.JSON(http.StatusOK, contract)
}

func (h *ContractHandler) CreateDedicatedVar(c *gin.Context) {
	var contract models.ContractDedicatedVar
	if err := c.ShouldBindJSON(&contract); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateDedicatedVar(&contract); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, contract)
}

func (h *ContractHandler) UpdateDedicatedVar(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	contract, err := h.service.GetDedicatedVarByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "contract not found"})
		return
	}
	bodyBytes, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "failed to read body"})
		return
	}
	if err := json.Unmarshal(bodyBytes, contract); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	contract.ID = uint(id)
	contract.Mill = models.Mill{}
	contract.Vendor = models.Vendor{}
	contract.Product = nil
	contract.OriginZone = nil
	contract.DestZone = nil
	contract.Mot = nil
	contract.Uom = nil

	changedBy := c.Query("changed_by")
	note := c.Query("note")

	if err := h.service.UpdateDedicatedVar(contract, changedBy, note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	updated, _ := h.service.GetDedicatedVarByID(uint(id))
	c.JSON(http.StatusOK, updated)
}

func (h *ContractHandler) DeleteDedicatedVar(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteDedicatedVar(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// UpdateDedicatedVarAgreement updates only the agreement note.
func (h *ContractHandler) UpdateDedicatedVarAgreement(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var body struct {
		ChangedBy string `json:"changed_by"`
		Note      string `json:"note"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.UpdateDedicatedVarAgreement(uint(id), body.ChangedBy, body.Note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "agreement updated"})
}

// --- Oncall ---

func (h *ContractHandler) GetAllOncall(c *gin.Context) {
	filters := make(map[string]interface{})
	search := c.Query("q")
	if v := c.Query("vendor_id"); v != "" {
		filters["vendor_id"] = v
	}
	if v := c.Query("mill_id"); v != "" {
		filters["mill_id"] = v
	}

	contracts, err := h.service.GetAllOncall(filters, search)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	total := len(contracts)
	c.Header("X-Total-Count", fmt.Sprintf("%d", total))
	c.Header("Access-Control-Expose-Headers", "X-Total-Count")

	startStr := c.DefaultQuery("_start", "0")
	endStr := c.DefaultQuery("_end", fmt.Sprintf("%d", total))
	start, _ := strconv.Atoi(startStr)
	end, _ := strconv.Atoi(endStr)
	if start < 0 {
		start = 0
	}
	if end > total {
		end = total
	}
	if start > total {
		start = total
	}
	c.JSON(http.StatusOK, contracts[start:end])
}

func (h *ContractHandler) GetOncallByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	contract, err := h.service.GetOncallByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "contract not found"})
		return
	}
	c.JSON(http.StatusOK, contract)
}

func (h *ContractHandler) CreateOncall(c *gin.Context) {
	var contract models.ContractOncall
	if err := c.ShouldBindJSON(&contract); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateOncall(&contract); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, contract)
}

func (h *ContractHandler) UpdateOncall(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	contract, err := h.service.GetOncallByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "contract not found"})
		return
	}
	bodyBytes, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "failed to read body"})
		return
	}
	if err := json.Unmarshal(bodyBytes, contract); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	contract.ID = uint(id)
	contract.Mill = models.Mill{}
	contract.Vendor = models.Vendor{}
	contract.Product = nil
	contract.OriginZone = nil
	contract.DestZone = nil
	contract.Mot = nil
	contract.Uom = nil

	changedBy := c.Query("changed_by")
	note := c.Query("note")

	if err := h.service.UpdateOncall(contract, changedBy, note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	updated, _ := h.service.GetOncallByID(uint(id))
	c.JSON(http.StatusOK, updated)
}

func (h *ContractHandler) DeleteOncall(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteOncall(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// UpdateOncallAgreement updates only the agreement note.
func (h *ContractHandler) UpdateOncallAgreement(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var body struct {
		ChangedBy string `json:"changed_by"`
		Note      string `json:"note"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.UpdateOncallAgreement(uint(id), body.ChangedBy, body.Note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "agreement updated"})
}

// --- Audit ---

func (h *ContractHandler) GetAuditHistory(c *gin.Context) {
	entityType := c.Param("entity_type")
	entityID, err := strconv.ParseUint(c.Param("entity_id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid entity_id"})
		return
	}
	logs, err := h.service.GetAuditHistory(entityType, uint(entityID))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, logs)
}

func (h *ContractHandler) GetVendorAuditHistory(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	logs, err := h.service.GetVendorAuditHistory(uint(id))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, logs)
}

func (h *ContractHandler) UpdateVendorAgreement(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var body struct {
		ChangedBy string `json:"changed_by"`
		Note      string `json:"note"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.UpdateVendorAgreement(uint(id), body.ChangedBy, body.Note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "vendor agreement updated"})
}

func (h *ContractHandler) UpdateMillAgreement(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var body struct {
		ChangedBy string `json:"changed_by"`
		Note      string `json:"note"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.UpdateMillAgreement(uint(id), body.ChangedBy, body.Note); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "mill agreement updated"})
}
