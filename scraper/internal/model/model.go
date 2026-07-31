// Package model defines the wire contract between the Go collector and the
// Python analysis API. The JSON tags here are mirrored one-for-one by the
// Pydantic models in api/app/contract.py — change one, change the other.
package model

import (
	"crypto/sha1"
	"encoding/hex"
	"strings"
	"time"
)

// Price is a money amount. Currency is an ISO-4217 code.
type Price struct {
	Amount   float64 `json:"amount"`
	Currency string  `json:"currency"`
}

// Review is a single customer review attached to a Product.
type Review struct {
	ID        string     `json:"id"`
	ProductID string     `json:"product_id"`
	Rating    float64    `json:"rating,omitempty"`
	Title     string     `json:"title,omitempty"`
	Body      string     `json:"body"`
	Author    string     `json:"author,omitempty"`
	PostedAt  *time.Time `json:"posted_at,omitempty"`
}

// Product is one competitor offering as seen on one source at one point in time.
type Product struct {
	ID          string            `json:"id"`
	Source      string            `json:"source"`
	URL         string            `json:"url"`
	Title       string            `json:"title"`
	Brand       string            `json:"brand,omitempty"`
	Category    string            `json:"category,omitempty"`
	Price       Price             `json:"price"`
	ListPrice   *Price            `json:"list_price,omitempty"`
	Rating      float64           `json:"rating,omitempty"`
	RatingCount int               `json:"rating_count,omitempty"`
	InStock     bool              `json:"in_stock"`
	Description string            `json:"description,omitempty"`
	Features    map[string]string `json:"features,omitempty"`
	Reviews     []Review          `json:"reviews,omitempty"`
	CollectedAt time.Time         `json:"collected_at"`
}

// MakeID builds a stable, source-scoped product id so re-running the collector
// upserts the same row instead of creating duplicates.
func MakeID(source, native string) string {
	return source + ":" + slug(native)
}

// MakeReviewID derives a deterministic review id from its content, because most
// sources do not expose one. Same review text + author => same id across runs.
func MakeReviewID(productID, author, body string) string {
	sum := sha1.Sum([]byte(productID + "|" + author + "|" + body))
	return productID + "#" + hex.EncodeToString(sum[:])[:10]
}

func slug(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	var b strings.Builder
	prevDash := false
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			b.WriteRune(r)
			prevDash = false
		default:
			if !prevDash && b.Len() > 0 {
				b.WriteByte('-')
				prevDash = true
			}
		}
	}
	return strings.Trim(b.String(), "-")
}
