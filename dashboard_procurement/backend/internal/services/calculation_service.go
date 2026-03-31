package services

import (
	"github.com/shopspring/decimal"
)

// CalculationService handles logistics cost calculations.
type CalculationService struct{}

// NewCalculationService creates a new CalculationService.
func NewCalculationService() *CalculationService {
	return &CalculationService{}
}

// CalcCostPerKGPerKM calculates cost per KG per KM.
// Formula: totalCost / (payload * distance)
func (s *CalculationService) CalcCostPerKGPerKM(totalCost, payload, distance decimal.Decimal) decimal.Decimal {
	denominator := payload.Mul(distance)
	if denominator.IsZero() {
		return decimal.Zero
	}
	return totalCost.Div(denominator).Round(4)
}

// CalcRunningCost calculates the running cost in IDR/Ton/KM.
// Formula: totalCost / (tonPayload * distance)
func (s *CalculationService) CalcRunningCost(totalCost, tonPayload, distance decimal.Decimal) decimal.Decimal {
	denominator := tonPayload.Mul(distance)
	if denominator.IsZero() {
		return decimal.Zero
	}
	return totalCost.Div(denominator).Round(4)
}

// CalcDistributedCost calculates the average distributed cost over months.
func (s *CalculationService) CalcDistributedCost(monthlyCosts []decimal.Decimal) decimal.Decimal {
	if len(monthlyCosts) == 0 {
		return decimal.Zero
	}

	total := decimal.Zero
	count := 0
	for _, cost := range monthlyCosts {
		if !cost.IsZero() {
			total = total.Add(cost)
			count++
		}
	}

	if count == 0 {
		return decimal.Zero
	}
	return total.Div(decimal.NewFromInt(int64(count))).Round(2)
}

// CalcTotalCostWithLoadUnload calculates total cost including loading and unloading.
func (s *CalculationService) CalcTotalCostWithLoadUnload(runningCost, distance, tonnage, loadCost, unloadCost decimal.Decimal) decimal.Decimal {
	freight := runningCost.Mul(distance).Mul(tonnage)
	return freight.Add(loadCost).Add(unloadCost).Round(2)
}
