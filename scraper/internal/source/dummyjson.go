package source

import (
	"context"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/model"
)

func init() { Register(&dummyJSON{}) }

// dummyJSON reads https://dummyjson.com — a public sandbox API that serves
// ~194 products across ~30 brands, each with price, discount, rating, stock and
// customer reviews. It is the richest legal stand-in for a real marketplace
// catalogue, and it is the source the competitor analysis actually runs on.
type dummyJSON struct{}

const dummyJSONPageSize = 30

func (d *dummyJSON) Name() string { return "dummyjson" }

func (d *dummyJSON) Discover(ctx context.Context, c *fetch.Client, limit int) ([]Task, error) {
	var head struct {
		Total int `json:"total"`
	}
	if err := c.JSON(ctx, "https://dummyjson.com/products?limit=1&select=id", &head); err != nil {
		return nil, err
	}

	total := head.Total
	if limit > 0 && limit < total {
		total = limit
	}
	var tasks []Task
	for skip := 0; skip < total; skip += dummyJSONPageSize {
		size := min(dummyJSONPageSize, total-skip)
		tasks = append(tasks, Task{
			URL: fmt.Sprintf("https://dummyjson.com/products?limit=%d&skip=%d", size, skip),
		})
	}
	return tasks, nil
}

func (d *dummyJSON) Fetch(ctx context.Context, c *fetch.Client, t Task) ([]model.Product, error) {
	var page struct {
		Products []dummyProduct `json:"products"`
	}
	if err := c.JSON(ctx, t.URL, &page); err != nil {
		return nil, err
	}

	now := time.Now().UTC()
	out := make([]model.Product, 0, len(page.Products))
	for _, p := range page.Products {
		out = append(out, p.toModel(now))
	}
	return out, nil
}

type dummyProduct struct {
	ID                 int      `json:"id"`
	Title              string   `json:"title"`
	Description        string   `json:"description"`
	Category           string   `json:"category"`
	Price              float64  `json:"price"`
	DiscountPercentage float64  `json:"discountPercentage"`
	Rating             float64  `json:"rating"`
	Stock              int      `json:"stock"`
	Tags               []string `json:"tags"`
	Brand              string   `json:"brand"`
	SKU                string   `json:"sku"`
	Warranty           string   `json:"warrantyInformation"`
	Shipping           string   `json:"shippingInformation"`
	Availability       string   `json:"availabilityStatus"`
	ReturnPolicy       string   `json:"returnPolicy"`
	MinOrderQty        int      `json:"minimumOrderQuantity"`
	Reviews            []struct {
		Rating       int    `json:"rating"`
		Comment      string `json:"comment"`
		Date         string `json:"date"`
		ReviewerName string `json:"reviewerName"`
	} `json:"reviews"`
}

func (p dummyProduct) toModel(now time.Time) model.Product {
	id := model.MakeID("dummyjson", strconv.Itoa(p.ID))

	// The API exposes a list price plus a discount percentage. Price
	// intelligence compares what a shopper actually pays, so Price is the
	// discounted figure and ListPrice keeps the original for discount-depth.
	effective := round2(p.Price * (1 - p.DiscountPercentage/100))
	product := model.Product{
		ID:          id,
		Source:      "dummyjson",
		URL:         fmt.Sprintf("https://dummyjson.com/products/%d", p.ID),
		Title:       p.Title,
		Brand:       strings.TrimSpace(p.Brand),
		Category:    p.Category,
		Price:       model.Price{Amount: effective, Currency: "USD"},
		Rating:      p.Rating,
		RatingCount: len(p.Reviews),
		InStock:     p.Stock > 0,
		Description: p.Description,
		Features: map[string]string{
			"sku":                    p.SKU,
			"warranty":               p.Warranty,
			"shipping":               p.Shipping,
			"return_policy":          p.ReturnPolicy,
			"availability":           p.Availability,
			"stock":                  strconv.Itoa(p.Stock),
			"minimum_order_quantity": strconv.Itoa(p.MinOrderQty),
			"tags":                   strings.Join(p.Tags, ", "),
		},
		CollectedAt: now,
	}
	if p.DiscountPercentage > 0 {
		product.ListPrice = &model.Price{Amount: round2(p.Price), Currency: "USD"}
	}
	if product.Brand == "" {
		product.Brand = "(unbranded)"
	}

	for _, r := range p.Reviews {
		review := model.Review{
			ID:        model.MakeReviewID(id, r.ReviewerName, r.Comment),
			ProductID: id,
			Rating:    float64(r.Rating),
			Body:      r.Comment,
			Author:    r.ReviewerName,
		}
		if ts, err := time.Parse(time.RFC3339, r.Date); err == nil {
			review.PostedAt = &ts
		}
		product.Reviews = append(product.Reviews, review)
	}
	return product
}

func round2(f float64) float64 { return math.Round(f*100) / 100 }
