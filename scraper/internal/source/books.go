package source

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/model"
)

func init() { Register(&books{}) }

// books reads https://books.toscrape.com — a site published expressly for
// scraping practice. It contributes the real HTML-parsing path: pagination,
// detail pages, messy availability strings and a specification table.
type books struct{}

const (
	booksBase       = "https://books.toscrape.com/catalogue/"
	booksPerPage    = 20
	booksMaxCatalog = 50 // catalogue pages to walk at most (1000 products)
)

func (b *books) Name() string { return "books" }

// Discover walks the catalogue pages and collects product detail URLs. It runs
// sequentially because each page is only known after the previous one loads;
// the expensive part — the detail pages — is what the worker pool parallelises.
func (b *books) Discover(ctx context.Context, c *fetch.Client, limit int) ([]Task, error) {
	if limit <= 0 {
		limit = booksPerPage * booksMaxCatalog
	}
	pages := (limit + booksPerPage - 1) / booksPerPage
	pages = min(pages, booksMaxCatalog)

	var tasks []Task
	for page := 1; page <= pages && len(tasks) < limit; page++ {
		doc, err := c.Doc(ctx, fmt.Sprintf("%spage-%d.html", booksBase, page))
		if err != nil {
			if page == 1 {
				return nil, err
			}
			break // ran past the last page; keep what we have
		}
		found := 0
		doc.Find("article.product_pod h3 a").EachWithBreak(func(_ int, s *goquery.Selection) bool {
			href, ok := s.Attr("href")
			if !ok {
				return true
			}
			tasks = append(tasks, Task{URL: booksBase + strings.TrimPrefix(href, "../../../")})
			found++
			return len(tasks) < limit
		})
		if found == 0 {
			break
		}
	}
	return tasks, nil
}

func (b *books) Fetch(ctx context.Context, c *fetch.Client, t Task) ([]model.Product, error) {
	doc, err := c.Doc(ctx, t.URL)
	if err != nil {
		return nil, err
	}

	title := strings.TrimSpace(doc.Find("div.product_main h1").First().Text())
	if title == "" {
		return nil, fmt.Errorf("books: no title at %s", t.URL)
	}

	specs := map[string]string{}
	doc.Find("table.table-striped tr").Each(func(_ int, s *goquery.Selection) {
		k := strings.TrimSpace(s.Find("th").Text())
		v := strings.TrimSpace(s.Find("td").Text())
		if k != "" {
			specs[strings.ToLower(strings.ReplaceAll(k, " ", "_"))] = v
		}
	})

	amount, currency := parseMoney(doc.Find("div.product_main p.price_color").First().Text())
	availability := strings.TrimSpace(doc.Find("div.product_main p.availability").Text())

	p := model.Product{
		ID:          model.MakeID("books", specs["upc"]),
		Source:      "books",
		URL:         t.URL,
		Title:       title,
		Brand:       "(unbranded)", // the catalogue has no brand axis; category carries the segmentation
		Category:    breadcrumbCategory(doc),
		Price:       model.Price{Amount: amount, Currency: currency},
		Rating:      starRating(doc),
		RatingCount: atoi(specs["number_of_reviews"]),
		InStock:     strings.Contains(availability, "In stock"),
		Description: strings.TrimSpace(doc.Find("#product_description ~ p").First().Text()),
		Features:    specs,
		CollectedAt: time.Now().UTC(),
	}
	if p.ID == "books:" {
		p.ID = model.MakeID("books", title)
	}
	p.Features["availability"] = availability
	return []model.Product{p}, nil
}

// breadcrumbCategory pulls the genre out of Home > Books > <genre> > <title>.
func breadcrumbCategory(doc *goquery.Document) string {
	links := doc.Find("ul.breadcrumb li a")
	if links.Length() >= 2 {
		return strings.TrimSpace(links.Eq(links.Length() - 1).Text())
	}
	return ""
}

var starWords = map[string]float64{"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

// starRating reads the rating out of the CSS class, e.g. <p class="star-rating Three">.
func starRating(doc *goquery.Document) float64 {
	class, _ := doc.Find("p.star-rating").First().Attr("class")
	for _, f := range strings.Fields(class) {
		if v, ok := starWords[f]; ok {
			return v
		}
	}
	return 0
}

// parseMoney turns "£51.77" or "$299" into (51.77, "GBP").
func parseMoney(s string) (float64, string) {
	s = strings.TrimSpace(s)
	currency := "USD"
	switch {
	case strings.HasPrefix(s, "£"):
		currency = "GBP"
	case strings.HasPrefix(s, "€"):
		currency = "EUR"
	case strings.HasPrefix(s, "฿"):
		currency = "THB"
	}
	var digits strings.Builder
	for _, r := range s {
		if (r >= '0' && r <= '9') || r == '.' {
			digits.WriteRune(r)
		}
	}
	amount, _ := strconv.ParseFloat(digits.String(), 64)
	return amount, currency
}

func atoi(s string) int {
	n, _ := strconv.Atoi(strings.TrimSpace(s))
	return n
}
