// Package store is where collected products go: a JSONL file on disk, or
// straight into the analysis API's /ingest endpoint.
package store

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"marketintel/scraper/internal/model"
)

// Writer accepts products one at a time and flushes on Close.
type Writer interface {
	Write(model.Product) error
	Close() error
}

// JSONL writes one product per line — append-friendly, streamable, and the
// format the Python ingester reads.
type JSONL struct {
	f   *os.File
	enc *json.Encoder
}

// NewJSONL creates path (and any missing parent directories).
func NewJSONL(path string) (*JSONL, error) {
	if dir := filepath.Dir(path); dir != "" {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, err
		}
	}
	f, err := os.Create(path)
	if err != nil {
		return nil, err
	}
	return &JSONL{f: f, enc: json.NewEncoder(f)}, nil
}

func (w *JSONL) Write(p model.Product) error { return w.enc.Encode(p) }
func (w *JSONL) Close() error                { return w.f.Close() }

// API posts products to the analysis service in batches.
type API struct {
	endpoint string
	batch    int
	client   *http.Client
	buf      []model.Product
}

// NewAPI targets an /ingest endpoint, e.g. http://localhost:8001/ingest.
func NewAPI(endpoint string, batch int) *API {
	if batch <= 0 {
		batch = 50
	}
	return &API{
		endpoint: endpoint,
		batch:    batch,
		client:   &http.Client{Timeout: 60 * time.Second},
	}
}

func (w *API) Write(p model.Product) error {
	w.buf = append(w.buf, p)
	if len(w.buf) >= w.batch {
		return w.flush()
	}
	return nil
}

func (w *API) Close() error { return w.flush() }

func (w *API) flush() error {
	if len(w.buf) == 0 {
		return nil
	}
	body, err := json.Marshal(map[string]any{"products": w.buf})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, w.endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := w.client.Do(req)
	if err != nil {
		return fmt.Errorf("store: posting %d products: %w", len(w.buf), err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 2<<10))
		return fmt.Errorf("store: %s returned %d: %s", w.endpoint, resp.StatusCode, bytes.TrimSpace(msg))
	}
	w.buf = w.buf[:0]
	return nil
}

// Multi fans every product out to several writers (file *and* API).
type Multi []Writer

func (m Multi) Write(p model.Product) error {
	for _, w := range m {
		if err := w.Write(p); err != nil {
			return err
		}
	}
	return nil
}

func (m Multi) Close() error {
	var firstErr error
	for _, w := range m {
		if err := w.Close(); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}
