package source

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/model"
)

// serve returns a client and a URL for a canned response, so adapter parsing is
// tested without touching the network.
func serve(t *testing.T, body string) (*fetch.Client, string) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	return fetch.New(fetch.Options{RPS: 1000, RespectRobots: false}), srv.URL
}

const dummyJSONFixture = `{"products":[{
  "id": 7, "title": "Rolex Submariner Watch", "description": "A luxury watch.",
  "category": "mens-watches", "price": 100, "discountPercentage": 25,
  "rating": 4.31, "stock": 0, "tags": ["mens","watches"], "brand": "Rolex",
  "sku": "MEN-WAT-ROL-007", "warrantyInformation": "2 year warranty",
  "shippingInformation": "Ships overnight", "availabilityStatus": "Out of Stock",
  "returnPolicy": "30 days return policy", "minimumOrderQuantity": 1,
  "reviews": [
    {"rating": 2, "comment": "Battery dies fast", "date": "2025-04-30T09:41:02.053Z", "reviewerName": "Ann Lee"},
    {"rating": 5, "comment": "Beautiful finish", "date": "not-a-date", "reviewerName": "Bo Ray"}
  ]}]}`

func TestDummyJSONMapping(t *testing.T) {
	c, url := serve(t, dummyJSONFixture)

	products, err := (&dummyJSON{}).Fetch(context.Background(), c, Task{URL: url})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if len(products) != 1 {
		t.Fatalf("got %d products, want 1", len(products))
	}
	p := products[0]

	if p.ID != "dummyjson:7" {
		t.Errorf("ID = %q, want dummyjson:7", p.ID)
	}
	// Price is what a shopper pays; ListPrice keeps the pre-discount figure.
	if p.Price.Amount != 75 {
		t.Errorf("Price = %v, want 75 (100 less 25%%)", p.Price.Amount)
	}
	if p.ListPrice == nil || p.ListPrice.Amount != 100 {
		t.Errorf("ListPrice = %v, want 100", p.ListPrice)
	}
	if p.InStock {
		t.Error("InStock = true, want false — stock is 0")
	}
	if p.Brand != "Rolex" || p.Category != "mens-watches" {
		t.Errorf("brand/category = %q/%q", p.Brand, p.Category)
	}
	if len(p.Reviews) != 2 {
		t.Fatalf("got %d reviews, want 2", len(p.Reviews))
	}
	if p.Reviews[0].ProductID != p.ID {
		t.Errorf("review is not linked to its product: %q", p.Reviews[0].ProductID)
	}
	if p.Reviews[0].PostedAt == nil {
		t.Error("valid RFC3339 date should be parsed")
	}
	if p.Reviews[1].PostedAt != nil {
		t.Error("an unparseable date must be dropped, not guessed")
	}
}

func TestDummyJSONReviewIDsAreStableAndUnique(t *testing.T) {
	c, url := serve(t, dummyJSONFixture)
	src := &dummyJSON{}

	first, err := src.Fetch(context.Background(), c, Task{URL: url})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	second, err := src.Fetch(context.Background(), c, Task{URL: url})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}

	// Re-running the collector must upsert, not duplicate.
	if first[0].Reviews[0].ID != second[0].Reviews[0].ID {
		t.Error("review ids must be stable across runs")
	}
	if first[0].Reviews[0].ID == first[0].Reviews[1].ID {
		t.Error("different reviews must get different ids")
	}
}

const booksFixture = `<html><body>
<ul class="breadcrumb">
  <li><a href="/index.html">Home</a></li>
  <li><a href="/catalogue/category/books_1/index.html">Books</a></li>
  <li><a href="/catalogue/category/books/poetry_23/index.html">Poetry</a></li>
  <li class="active">A Light in the Attic</li>
</ul>
<div class="product_main">
  <h1>A Light in the Attic</h1>
  <p class="price_color">&pound;51.77</p>
  <p class="instock availability"><i class="icon-ok"></i> In stock (22 available)</p>
  <p class="star-rating Three"></p>
</div>
<div id="product_description"></div><p>It's hard to imagine a world without A Light in the Attic.</p>
<table class="table table-striped">
  <tr><th>UPC</th><td>a897fe39b1053632</td></tr>
  <tr><th>Number of reviews</th><td>7</td></tr>
</table>
</body></html>`

func TestBooksParsing(t *testing.T) {
	c, url := serve(t, booksFixture)

	products, err := (&books{}).Fetch(context.Background(), c, Task{URL: url})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	p := products[0]

	if p.ID != "books:a897fe39b1053632" {
		t.Errorf("ID = %q, want books:a897fe39b1053632", p.ID)
	}
	if p.Price.Amount != 51.77 || p.Price.Currency != "GBP" {
		t.Errorf("price = %v %s, want 51.77 GBP", p.Price.Amount, p.Price.Currency)
	}
	if p.Rating != 3 {
		t.Errorf("Rating = %v, want 3 — read from the star-rating class", p.Rating)
	}
	if p.Category != "Poetry" {
		t.Errorf("Category = %q, want Poetry", p.Category)
	}
	if !p.InStock {
		t.Error("InStock = false, want true")
	}
	if p.RatingCount != 7 {
		t.Errorf("RatingCount = %d, want 7", p.RatingCount)
	}
	if p.Description == "" {
		t.Error("description should be picked up from the paragraph after #product_description")
	}
}

func TestBooksRejectsPagesWithoutATitle(t *testing.T) {
	c, url := serve(t, "<html><body><p>404 not a product</p></body></html>")

	if _, err := (&books{}).Fetch(context.Background(), c, Task{URL: url}); err == nil {
		t.Fatal("Fetch succeeded on a non-product page, want an error so the runner counts it as failed")
	}
}

const scrapemeFixture = `<html><body><ul class="products columns-4">
<li class="product type-product post-759 status-publish first instock product_cat-pokemon product_cat-seed product_tag-bulbasaur has-post-thumbnail">
  <a href="https://scrapeme.live/shop/Bulbasaur/" class="woocommerce-LoopProduct-link">
    <h2 class="woocommerce-loop-product__title">Bulbasaur</h2>
    <span class="price"><span class="amount"><bdi><span>&pound;</span>63.00</bdi></span></span>
  </a>
</li>
<li class="product type-product post-760 outofstock product_cat-pokemon product_cat-fire">
  <a href="https://scrapeme.live/shop/Charmander/" class="woocommerce-LoopProduct-link">
    <h2 class="woocommerce-loop-product__title">Charmander</h2>
    <span class="price"><span class="amount"><bdi><span>&pound;</span>165.00</bdi></span></span>
  </a>
</li>
</ul></body></html>`

func TestScrapemeParsing(t *testing.T) {
	c, url := serve(t, scrapemeFixture)

	products, err := (&scrapeme{}).Fetch(context.Background(), c, Task{URL: url})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if len(products) != 2 {
		t.Fatalf("got %d products, want 2 — both listing cards", len(products))
	}

	if products[0].Category != "seed" {
		t.Errorf("Category = %q, want seed — the catch-all 'pokemon' bucket is skipped", products[0].Category)
	}
	if !products[0].InStock || products[1].InStock {
		t.Error("stock state comes from the instock/outofstock class")
	}
	if products[1].Price.Amount != 165 {
		t.Errorf("price = %v, want 165", products[1].Price.Amount)
	}
}

func TestRegistryExposesEverySource(t *testing.T) {
	names := Names()
	if len(names) < 3 {
		t.Fatalf("registered sources = %v, want at least dummyjson, books, scrapeme", names)
	}
	for _, want := range []string{"books", "dummyjson", "scrapeme"} {
		if _, err := Get(want); err != nil {
			t.Errorf("Get(%q): %v", want, err)
		}
	}
	if _, err := Get("shopee"); err == nil {
		t.Error("Get on an unregistered source should fail loudly")
	}
}

func TestMakeIDIsStableAndSlugged(t *testing.T) {
	if got := model.MakeID("books", "A Light in the Attic"); got != "books:a-light-in-the-attic" {
		t.Errorf("MakeID = %q", got)
	}
	if model.MakeID("a", "x") == model.MakeID("b", "x") {
		t.Error("ids must be scoped by source")
	}
}
