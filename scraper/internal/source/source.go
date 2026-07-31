// Package source holds the per-platform adapters. Adding a new competitor
// platform means adding one file here that implements Source and calls
// Register in its init — nothing else in the collector changes.
package source

import (
	"context"
	"fmt"
	"sort"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/model"
)

// Task is one unit of work: a page to fetch. Splitting discovery from fetching
// is what lets the runner spread any source across a worker pool without the
// adapter knowing anything about concurrency.
type Task struct {
	URL  string
	Meta map[string]string
}

// Source is a competitor data platform.
type Source interface {
	// Name is the id used on the command line and stored on every product.
	Name() string
	// Discover lists the work. limit caps the number of products the caller
	// wants; adapters should translate that into as few tasks as possible.
	Discover(ctx context.Context, c *fetch.Client, limit int) ([]Task, error)
	// Fetch turns one task into zero or more products. It must be safe to call
	// concurrently from many goroutines.
	Fetch(ctx context.Context, c *fetch.Client, t Task) ([]model.Product, error)
}

var registry = map[string]Source{}

// Register adds a source to the registry. Called from adapter init functions.
func Register(s Source) {
	if _, dup := registry[s.Name()]; dup {
		panic("source: duplicate registration for " + s.Name())
	}
	registry[s.Name()] = s
}

// Get looks up a registered source by name.
func Get(name string) (Source, error) {
	s, ok := registry[name]
	if !ok {
		return nil, fmt.Errorf("source: unknown source %q (available: %v)", name, Names())
	}
	return s, nil
}

// Names lists every registered source, sorted.
func Names() []string {
	names := make([]string, 0, len(registry))
	for n := range registry {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}

// All returns every registered source, sorted by name.
func All() []Source {
	out := make([]Source, 0, len(registry))
	for _, n := range Names() {
		out = append(out, registry[n])
	}
	return out
}
