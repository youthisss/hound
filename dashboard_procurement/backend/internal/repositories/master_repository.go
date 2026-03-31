package repositories

import (
	"rygell-dashboard/internal/models"

	"gorm.io/gorm"
)

// MasterRepository handles CRUD for all master data entities.
type MasterRepository struct {
	db *gorm.DB
}

// NewMasterRepository creates a new MasterRepository.
func NewMasterRepository(db *gorm.DB) *MasterRepository {
	return &MasterRepository{db: db}
}

// --- Mill ---

func (r *MasterRepository) GetAllMills(search string) ([]models.Mill, error) {
	var mills []models.Mill
	query := r.db
	if search != "" {
		like := "%" + search + "%"
		query = query.Where("name ILIKE ? OR code ILIKE ?", like, like)
	}
	err := query.Order("id ASC").Find(&mills).Error
	return mills, err
}

func (r *MasterRepository) GetMillByID(id uint) (*models.Mill, error) {
	var mill models.Mill
	err := r.db.First(&mill, id).Error
	return &mill, err
}

func (r *MasterRepository) CreateMill(mill *models.Mill) error {
	return r.db.Create(mill).Error
}

func (r *MasterRepository) UpdateMill(mill *models.Mill) error {
	return r.db.Save(mill).Error
}

func (r *MasterRepository) DeleteMill(id uint) error {
	return r.db.Delete(&models.Mill{}, id).Error
}

// --- Vendor ---

func (r *MasterRepository) GetAllVendors(search string) ([]models.Vendor, error) {
	var vendors []models.Vendor
	query := r.db
	if search != "" {
		like := "%" + search + "%"
		query = query.Where("name ILIKE ? OR code ILIKE ? OR email ILIKE ? OR contact_person ILIKE ?", like, like, like, like)
	}
	err := query.Order("id ASC").Find(&vendors).Error
	return vendors, err
}

func (r *MasterRepository) GetVendorByID(id uint) (*models.Vendor, error) {
	var vendor models.Vendor
	err := r.db.First(&vendor, id).Error
	return &vendor, err
}

func (r *MasterRepository) CreateVendor(vendor *models.Vendor) error {
	return r.db.Create(vendor).Error
}

func (r *MasterRepository) UpdateVendor(vendor *models.Vendor) error {
	return r.db.Save(vendor).Error
}

func (r *MasterRepository) DeleteVendor(id uint) error {
	return r.db.Delete(&models.Vendor{}, id).Error
}

// --- Product ---

func (r *MasterRepository) GetAllProducts() ([]models.Product, error) {
	var products []models.Product
	err := r.db.Find(&products).Error
	return products, err
}

func (r *MasterRepository) GetProductByID(id uint) (*models.Product, error) {
	var product models.Product
	err := r.db.First(&product, id).Error
	return &product, err
}

func (r *MasterRepository) CreateProduct(product *models.Product) error {
	return r.db.Create(product).Error
}

func (r *MasterRepository) UpdateProduct(product *models.Product) error {
	return r.db.Save(product).Error
}

func (r *MasterRepository) DeleteProduct(id uint) error {
	return r.db.Delete(&models.Product{}, id).Error
}

// --- Zone ---

func (r *MasterRepository) GetAllZones() ([]models.Zone, error) {
	var zones []models.Zone
	err := r.db.Find(&zones).Error
	return zones, err
}

func (r *MasterRepository) GetZoneByID(id uint) (*models.Zone, error) {
	var zone models.Zone
	err := r.db.First(&zone, id).Error
	return &zone, err
}

func (r *MasterRepository) CreateZone(zone *models.Zone) error {
	return r.db.Create(zone).Error
}

func (r *MasterRepository) UpdateZone(zone *models.Zone) error {
	return r.db.Save(zone).Error
}

func (r *MasterRepository) DeleteZone(id uint) error {
	return r.db.Delete(&models.Zone{}, id).Error
}

// --- MOT ---

func (r *MasterRepository) GetAllMots() ([]models.Mot, error) {
	var mots []models.Mot
	err := r.db.Find(&mots).Error
	return mots, err
}

func (r *MasterRepository) GetMotByID(id uint) (*models.Mot, error) {
	var mot models.Mot
	err := r.db.First(&mot, id).Error
	return &mot, err
}

func (r *MasterRepository) CreateMot(mot *models.Mot) error {
	return r.db.Create(mot).Error
}

func (r *MasterRepository) UpdateMot(mot *models.Mot) error {
	return r.db.Save(mot).Error
}

func (r *MasterRepository) DeleteMot(id uint) error {
	return r.db.Delete(&models.Mot{}, id).Error
}

// --- UOM ---

func (r *MasterRepository) GetAllUoms() ([]models.Uom, error) {
	var uoms []models.Uom
	err := r.db.Find(&uoms).Error
	return uoms, err
}

func (r *MasterRepository) GetUomByID(id uint) (*models.Uom, error) {
	var uom models.Uom
	err := r.db.First(&uom, id).Error
	return &uom, err
}

func (r *MasterRepository) CreateUom(uom *models.Uom) error {
	return r.db.Create(uom).Error
}

func (r *MasterRepository) UpdateUom(uom *models.Uom) error {
	return r.db.Save(uom).Error
}

func (r *MasterRepository) DeleteUom(id uint) error {
	return r.db.Delete(&models.Uom{}, id).Error
}

// --- Bulk Operations ---

func (r *MasterRepository) BulkCreateMills(mills []models.Mill) error {
	return r.db.CreateInBatches(mills, 100).Error
}

func (r *MasterRepository) BulkCreateVendors(vendors []models.Vendor) error {
	return r.db.CreateInBatches(vendors, 100).Error
}

func (r *MasterRepository) BulkCreateProducts(products []models.Product) error {
	return r.db.CreateInBatches(products, 100).Error
}

func (r *MasterRepository) BulkCreateZones(zones []models.Zone) error {
	return r.db.CreateInBatches(zones, 100).Error
}

// --- Find or Create (Upsert by Name) ---

// FindOrCreateVendorByName finds a vendor by name, or creates one if not found.
func (r *MasterRepository) FindOrCreateVendorByName(name string) (*models.Vendor, error) {
	var vendor models.Vendor
	err := r.db.Where("name = ?", name).First(&vendor).Error
	if err == nil {
		return &vendor, nil
	}
	vendor = models.Vendor{Name: name, Code: name}
	if err := r.db.Create(&vendor).Error; err != nil {
		return nil, err
	}
	return &vendor, nil
}

// FindOrCreateMillByName finds a mill by name, or creates one if not found.
func (r *MasterRepository) FindOrCreateMillByName(name string) (*models.Mill, error) {
	var mill models.Mill
	err := r.db.Where("name = ?", name).First(&mill).Error
	if err == nil {
		return &mill, nil
	}
	mill = models.Mill{Name: name, Code: name}
	if err := r.db.Create(&mill).Error; err != nil {
		return nil, err
	}
	return &mill, nil
}

// FindOrCreateProductByName finds a product by name, or creates one if not found.
func (r *MasterRepository) FindOrCreateProductByName(name string) (*models.Product, error) {
	var product models.Product
	err := r.db.Where("name = ?", name).First(&product).Error
	if err == nil {
		return &product, nil
	}
	product = models.Product{Name: name}
	if err := r.db.Create(&product).Error; err != nil {
		return nil, err
	}
	return &product, nil
}

// FindOrCreateZoneByName finds a zone by name, or creates one if not found.
func (r *MasterRepository) FindOrCreateZoneByName(name string) (*models.Zone, error) {
	var zone models.Zone
	err := r.db.Where("name = ?", name).First(&zone).Error
	if err == nil {
		return &zone, nil
	}
	zone = models.Zone{Name: name}
	if err := r.db.Create(&zone).Error; err != nil {
		return nil, err
	}
	return &zone, nil
}

// FindOrCreateMotByName finds a MOT by name, or creates one if not found.
func (r *MasterRepository) FindOrCreateMotByName(name string) (*models.Mot, error) {
	var mot models.Mot
	err := r.db.Where("name = ?", name).First(&mot).Error
	if err == nil {
		return &mot, nil
	}
	mot = models.Mot{Name: name}
	if err := r.db.Create(&mot).Error; err != nil {
		return nil, err
	}
	return &mot, nil
}

// FindOrCreateUomByName finds a UOM by name, or creates one if not found.
func (r *MasterRepository) FindOrCreateUomByName(name string) (*models.Uom, error) {
	var uom models.Uom
	err := r.db.Where("name = ?", name).First(&uom).Error
	if err == nil {
		return &uom, nil
	}
	uom = models.Uom{Name: name}
	if err := r.db.Create(&uom).Error; err != nil {
		return nil, err
	}
	return &uom, nil
}
