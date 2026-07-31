package source

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/model"
)

func init() { Register(&scrapeme{}) }

// scrapeme reads https://scrapeme.live/shop — a WooCommerce storefront put
// online for scraping practice. Everything needed is on the listing pages, so a
// 700-product catalogue costs ~15 requests instead of 700.
//
// It replaced an earlier webscraper.io adapter: that site's robots.txt carries
// "Disallow: /test-sites/e-commerce/", the fetch layer refused every request,
// and the right fix was to change source rather than to switch the check off.
type scrapeme struct{}

const (
	scrapemeBase     = "https://scrapeme.live/shop/"
	scrapemePerPage  = 16
	scrapemeMaxPages = 48
)

func (s *scrapeme) Name() string { return "scrapeme" }

func (s *scrapeme) Discover(_ context.Context, _ *fetch.Client, limit int) ([]Task, error) {
	pages := scrapemeMaxPages
	if limit > 0 {
		pages = min((limit+scrapemePerPage-1)/scrapemePerPage, scrapemeMaxPages)
	}
	tasks := make([]Task, 0, pages)
	for page := 1; page <= pages; page++ {
		url := scrapemeBase
		if page > 1 {
			url = fmt.Sprintf("%spage/%d/", scrapemeBase, page)
		}
		tasks = append(tasks, Task{URL: url})
	}
	return tasks, nil
}

func (s *scrapeme) Fetch(ctx context.Context, c *fetch.Client, t Task) ([]model.Product, error) {
	doc, err := c.Doc(ctx, t.URL)
	if err != nil {
		return nil, err
	}

	now := time.Now().UTC()
	var out []model.Product
	doc.Find("ul.products li.product").Each(func(_ int, sel *goquery.Selection) {
		title := strings.TrimSpace(sel.Find("h2.woocommerce-loop-product__title").First().Text())
		if title == "" {
			return
		}
		href, _ := sel.Find("a.woocommerce-LoopProduct-link").First().Attr("href")
		amount, currency := parseMoney(sel.Find("span.price bdi").First().Text())

		// WooCommerce encodes taxonomy and stock state in the <li> class list:
		// "product_cat-fire product_tag-charizard instock".
		classes := strings.Fields(sel.AttrOr("class", ""))
		var cats, tags []string
		inStock := false
		for _, cl := range classes {
			switch {
			case strings.HasPrefix(cl, "product_cat-"):
				cats = append(cats, strings.TrimPrefix(cl, "product_cat-"))
			case strings.HasPrefix(cl, "product_tag-"):
				tags = append(tags, strings.TrimPrefix(cl, "product_tag-"))
			case cl == "instock":
				inStock = true
			}
		}

		out = append(out, model.Product{
			ID:       model.MakeID("scrapeme", title),
			Source:   "scrapeme",
			URL:      href,
			Title:    title,
			Brand:    "(unbranded)",
			Category: primaryCategory(cats),
			Price:    model.Price{Amount: amount, Currency: currency},
			InStock:  inStock,
			Features: map[string]string{
				"categories": strings.Join(cats, ", "),
				"tags":       strings.Join(tags, ", "),
			},
			CollectedAt: now,
		})
	})
	if len(out) == 0 {
		return nil, fmt.Errorf("scrapeme: no products on %s", t.URL)
	}
	return out, nil
}

// primaryCategory skips the catch-all bucket every item belongs to and returns
// the first meaningful one.
func primaryCategory(cats []string) string {
	for _, c := range cats {
		if c != "pokemon" {
			return c
		}
	}
	if len(cats) > 0 {
		return cats[0]
	}
	return ""
}
