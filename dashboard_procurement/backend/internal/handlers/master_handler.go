package handlers

import (
	"fmt"
	"net/http"
	"strconv"

	"rygell-dashboard/internal/models"
	"rygell-dashboard/internal/services"

	"github.com/gin-gonic/gin"
)

// paginateAndRespond is a helper that handles simple-rest compatible pagination.
// It sets X-Total-Count header and slices the data based on _start/_end query params.
func paginateAndRespond[T any](c *gin.Context, data []T) {
	total := len(data)
	c.Header("X-Total-Count", fmt.Sprintf("%d", total))
	c.Header("Access-Control-Expose-Headers", "X-Total-Count")

	// Parse _start and _end for simple-rest pagination
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

	// Handle _sort and _order
	sortField := c.DefaultQuery("_sort", "id")
	sortOrder := c.DefaultQuery("_order", "ASC")
	_ = sortField
	_ = sortOrder

	c.JSON(http.StatusOK, data[start:end])
}

// MasterHandler handles HTTP requests for master data.
type MasterHandler struct {
	service *services.MasterService
}

// NewMasterHandler creates a new MasterHandler.
func NewMasterHandler(service *services.MasterService) *MasterHandler {
	return &MasterHandler{service: service}
}

// --- Mill ---

func (h *MasterHandler) GetAllMills(c *gin.Context) {
	search := c.Query("q")
	mills, err := h.service.GetAllMills(search)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	paginateAndRespond(c, mills)
}

func (h *MasterHandler) GetMillByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	mill, err := h.service.GetMillByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "mill not found"})
		return
	}
	c.JSON(http.StatusOK, mill)
}

func (h *MasterHandler) CreateMill(c *gin.Context) {
	var mill models.Mill
	if err := c.ShouldBindJSON(&mill); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateMill(&mill); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, mill)
}

func (h *MasterHandler) UpdateMill(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var mill models.Mill
	if err := c.ShouldBindJSON(&mill); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	mill.ID = uint(id)
	if err := h.service.UpdateMill(&mill); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, mill)
}

func (h *MasterHandler) DeleteMill(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteMill(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// --- Vendor ---

func (h *MasterHandler) GetAllVendors(c *gin.Context) {
	search := c.Query("q")
	vendors, err := h.service.GetAllVendors(search)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	paginateAndRespond(c, vendors)
}

func (h *MasterHandler) GetVendorByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	vendor, err := h.service.GetVendorByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "vendor not found"})
		return
	}
	c.JSON(http.StatusOK, vendor)
}

func (h *MasterHandler) CreateVendor(c *gin.Context) {
	var vendor models.Vendor
	if err := c.ShouldBindJSON(&vendor); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateVendor(&vendor); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, vendor)
}

func (h *MasterHandler) UpdateVendor(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var vendor models.Vendor
	if err := c.ShouldBindJSON(&vendor); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	vendor.ID = uint(id)
	if err := h.service.UpdateVendor(&vendor); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, vendor)
}

func (h *MasterHandler) DeleteVendor(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteVendor(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// --- Product ---

func (h *MasterHandler) GetAllProducts(c *gin.Context) {
	products, err := h.service.GetAllProducts()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	paginateAndRespond(c, products)
}

func (h *MasterHandler) GetProductByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	product, err := h.service.GetProductByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "product not found"})
		return
	}
	c.JSON(http.StatusOK, product)
}

func (h *MasterHandler) CreateProduct(c *gin.Context) {
	var product models.Product
	if err := c.ShouldBindJSON(&product); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateProduct(&product); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, product)
}

func (h *MasterHandler) UpdateProduct(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var product models.Product
	if err := c.ShouldBindJSON(&product); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	product.ID = uint(id)
	if err := h.service.UpdateProduct(&product); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, product)
}

func (h *MasterHandler) DeleteProduct(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteProduct(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// --- Zone ---

func (h *MasterHandler) GetAllZones(c *gin.Context) {
	zones, err := h.service.GetAllZones()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	paginateAndRespond(c, zones)
}

func (h *MasterHandler) GetZoneByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	zone, err := h.service.GetZoneByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "zone not found"})
		return
	}
	c.JSON(http.StatusOK, zone)
}

func (h *MasterHandler) CreateZone(c *gin.Context) {
	var zone models.Zone
	if err := c.ShouldBindJSON(&zone); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateZone(&zone); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, zone)
}

func (h *MasterHandler) UpdateZone(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var zone models.Zone
	if err := c.ShouldBindJSON(&zone); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	zone.ID = uint(id)
	if err := h.service.UpdateZone(&zone); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, zone)
}

func (h *MasterHandler) DeleteZone(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteZone(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// --- MOT ---

func (h *MasterHandler) GetAllMots(c *gin.Context) {
	mots, err := h.service.GetAllMots()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	paginateAndRespond(c, mots)
}

func (h *MasterHandler) GetMotByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	mot, err := h.service.GetMotByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "mot not found"})
		return
	}
	c.JSON(http.StatusOK, mot)
}

func (h *MasterHandler) CreateMot(c *gin.Context) {
	var mot models.Mot
	if err := c.ShouldBindJSON(&mot); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateMot(&mot); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, mot)
}

func (h *MasterHandler) UpdateMot(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var mot models.Mot
	if err := c.ShouldBindJSON(&mot); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	mot.ID = uint(id)
	if err := h.service.UpdateMot(&mot); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, mot)
}

func (h *MasterHandler) DeleteMot(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteMot(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// --- UOM ---

func (h *MasterHandler) GetAllUoms(c *gin.Context) {
	uoms, err := h.service.GetAllUoms()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	paginateAndRespond(c, uoms)
}

func (h *MasterHandler) GetUomByID(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	uom, err := h.service.GetUomByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "uom not found"})
		return
	}
	c.JSON(http.StatusOK, uom)
}

func (h *MasterHandler) CreateUom(c *gin.Context) {
	var uom models.Uom
	if err := c.ShouldBindJSON(&uom); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if err := h.service.CreateUom(&uom); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, uom)
}

func (h *MasterHandler) UpdateUom(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	var uom models.Uom
	if err := c.ShouldBindJSON(&uom); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	uom.ID = uint(id)
	if err := h.service.UpdateUom(&uom); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, uom)
}

func (h *MasterHandler) DeleteUom(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	if err := h.service.DeleteUom(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}
