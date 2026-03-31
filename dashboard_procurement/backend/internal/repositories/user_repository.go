package repositories

import (
	"rygell-dashboard/internal/models"

	"gorm.io/gorm"
)

// UserRepository handles user credential queries.
type UserRepository struct {
	db *gorm.DB
}

func NewUserRepository(db *gorm.DB) *UserRepository {
	return &UserRepository{db: db}
}

func (r *UserRepository) Create(user *models.User) error {
	return r.db.Create(user).Error
}

func (r *UserRepository) FindByUsername(username string) (*models.User, error) {
	var user models.User
	if err := r.db.Where("username = ?", username).First(&user).Error; err != nil {
		return nil, err
	}
	return &user, nil
}

func (r *UserRepository) FindByID(id uint) (*models.User, error) {
	var user models.User
	if err := r.db.First(&user, id).Error; err != nil {
		return nil, err
	}
	return &user, nil
}

func (r *UserRepository) Count() (int64, error) {
	var total int64
	if err := r.db.Model(&models.User{}).Count(&total).Error; err != nil {
		return 0, err
	}
	return total, nil
}
