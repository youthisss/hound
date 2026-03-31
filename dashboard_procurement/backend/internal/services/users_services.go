package services

import (
	"errors"
	"fmt"
	"strconv"
	"time"

	"rygell-dashboard/internal/models"
	"rygell-dashboard/internal/repositories"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"
)

// UserService handles authentication and user bootstrap.
type UserService struct {
	repo           *repositories.UserRepository
	jwtSecret      string
	jwtExpiryHours int
}

func NewUserService(repo *repositories.UserRepository, jwtSecret string, jwtExpiryHours string) *UserService {
	expiry := 24
	if h, err := strconv.Atoi(jwtExpiryHours); err == nil && h > 0 {
		expiry = h
	}
	return &UserService{
		repo:           repo,
		jwtSecret:      jwtSecret,
		jwtExpiryHours: expiry,
	}
}

func (s *UserService) EnsureDefaultAdmin(name, username, password string) error {
	total, err := s.repo.Count()
	if err != nil {
		return err
	}
	if total > 0 {
		return nil
	}
	_, err = s.CreateUser(name, username, password)
	return err
}

func (s *UserService) CreateUser(name, username, password string) (*models.User, error) {
	if username == "" || password == "" || name == "" {
		return nil, errors.New("name, username, and password are required")
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return nil, err
	}

	user := &models.User{
		Name:         name,
		Username:     username,
		PasswordHash: string(hash),
	}
	if err := s.repo.Create(user); err != nil {
		return nil, err
	}
	return user, nil
}

func (s *UserService) Login(username, password string) (string, *models.User, error) {
	user, err := s.repo.FindByUsername(username)
	if err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return "", nil, errors.New("invalid username or password")
		}
		return "", nil, err
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(password)); err != nil {
		return "", nil, errors.New("invalid username or password")
	}

	claims := jwt.MapClaims{
		"sub":      user.ID,
		"username": user.Username,
		"exp":      time.Now().Add(time.Duration(s.jwtExpiryHours) * time.Hour).Unix(),
		"iat":      time.Now().Unix(),
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := token.SignedString([]byte(s.jwtSecret))
	if err != nil {
		return "", nil, err
	}

	return signed, user, nil
}

func (s *UserService) GetByID(id uint) (*models.User, error) {
	return s.repo.FindByID(id)
}

func (s *UserService) ParseToken(rawToken string) (jwt.MapClaims, error) {
	token, err := jwt.Parse(rawToken, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return []byte(s.jwtSecret), nil
	})
	if err != nil {
		return nil, err
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok || !token.Valid {
		return nil, errors.New("invalid token")
	}
	return claims, nil
}
