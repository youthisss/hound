package services

import (
	"rygell-dashboard/internal/models"
	"rygell-dashboard/internal/repositories"
)

// MasterService handles business logic for master data.
type MasterService struct {
	repo *repositories.MasterRepository
}

// NewMasterService creates a new MasterService.
func NewMasterService(repo *repositories.MasterRepository) *MasterService {
	return &MasterService{repo: repo}
}

// --- Mill ---

func (s *MasterService) GetAllMills(search string) ([]models.Mill, error) {
	return s.repo.GetAllMills(search)
}

func (s *MasterService) GetMillByID(id uint) (*models.Mill, error) {
	return s.repo.GetMillByID(id)
}

func (s *MasterService) CreateMill(mill *models.Mill) error {
	return s.repo.CreateMill(mill)
}

func (s *MasterService) UpdateMill(mill *models.Mill) error {
	return s.repo.UpdateMill(mill)
}

func (s *MasterService) DeleteMill(id uint) error {
	return s.repo.DeleteMill(id)
}

// --- Vendor ---

func (s *MasterService) GetAllVendors(search string) ([]models.Vendor, error) {
	return s.repo.GetAllVendors(search)
}

func (s *MasterService) GetVendorByID(id uint) (*models.Vendor, error) {
	return s.repo.GetVendorByID(id)
}

func (s *MasterService) CreateVendor(vendor *models.Vendor) error {
	return s.repo.CreateVendor(vendor)
}

func (s *MasterService) UpdateVendor(vendor *models.Vendor) error {
	return s.repo.UpdateVendor(vendor)
}

func (s *MasterService) DeleteVendor(id uint) error {
	return s.repo.DeleteVendor(id)
}

// --- Product ---

func (s *MasterService) GetAllProducts() ([]models.Product, error) {
	return s.repo.GetAllProducts()
}

func (s *MasterService) GetProductByID(id uint) (*models.Product, error) {
	return s.repo.GetProductByID(id)
}

func (s *MasterService) CreateProduct(product *models.Product) error {
	return s.repo.CreateProduct(product)
}

func (s *MasterService) UpdateProduct(product *models.Product) error {
	return s.repo.UpdateProduct(product)
}

func (s *MasterService) DeleteProduct(id uint) error {
	return s.repo.DeleteProduct(id)
}

// --- Zone ---

func (s *MasterService) GetAllZones() ([]models.Zone, error) {
	return s.repo.GetAllZones()
}

func (s *MasterService) GetZoneByID(id uint) (*models.Zone, error) {
	return s.repo.GetZoneByID(id)
}

func (s *MasterService) CreateZone(zone *models.Zone) error {
	return s.repo.CreateZone(zone)
}

func (s *MasterService) UpdateZone(zone *models.Zone) error {
	return s.repo.UpdateZone(zone)
}

func (s *MasterService) DeleteZone(id uint) error {
	return s.repo.DeleteZone(id)
}

// --- MOT ---

func (s *MasterService) GetAllMots() ([]models.Mot, error) {
	return s.repo.GetAllMots()
}

func (s *MasterService) GetMotByID(id uint) (*models.Mot, error) {
	return s.repo.GetMotByID(id)
}

func (s *MasterService) CreateMot(mot *models.Mot) error {
	return s.repo.CreateMot(mot)
}

func (s *MasterService) UpdateMot(mot *models.Mot) error {
	return s.repo.UpdateMot(mot)
}

func (s *MasterService) DeleteMot(id uint) error {
	return s.repo.DeleteMot(id)
}

// --- UOM ---

func (s *MasterService) GetAllUoms() ([]models.Uom, error) {
	return s.repo.GetAllUoms()
}

func (s *MasterService) GetUomByID(id uint) (*models.Uom, error) {
	return s.repo.GetUomByID(id)
}

func (s *MasterService) CreateUom(uom *models.Uom) error {
	return s.repo.CreateUom(uom)
}

func (s *MasterService) UpdateUom(uom *models.Uom) error {
	return s.repo.UpdateUom(uom)
}

func (s *MasterService) DeleteUom(id uint) error {
	return s.repo.DeleteUom(id)
}
