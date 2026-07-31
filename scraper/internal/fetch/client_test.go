package fetch

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// fastClient keeps the backoff short so the retry tests stay in milliseconds.
func fastClient(opts Options) *Client {
	if opts.BaseBackoff == 0 {
		opts.BaseBackoff = time.Millisecond
	}
	if opts.RPS == 0 {
		opts.RPS = 1000
	}
	return New(opts)
}

func TestGetRetriesTransientFailures(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) < 3 {
			w.WriteHeader(http.StatusBadGateway)
			return
		}
		w.Write([]byte("ok"))
	}))
	defer srv.Close()

	body, err := fastClient(Options{MaxRetries: 3}).Get(context.Background(), srv.URL)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if string(body) != "ok" {
		t.Fatalf("body = %q, want %q", body, "ok")
	}
	if got := calls.Load(); got != 3 {
		t.Fatalf("server saw %d calls, want 3", got)
	}
}

func TestGetDoesNotRetryClientErrors(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	_, err := fastClient(Options{MaxRetries: 3}).Get(context.Background(), srv.URL)

	var se *StatusError
	if !errors.As(err, &se) || se.Code != http.StatusNotFound {
		t.Fatalf("err = %v, want StatusError 404", err)
	}
	if got := calls.Load(); got != 1 {
		t.Fatalf("server saw %d calls, want 1 — 404 is deterministic and must not be retried", got)
	}
}

func TestGetGivesUpAfterMaxRetries(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	if _, err := fastClient(Options{MaxRetries: 2}).Get(context.Background(), srv.URL); err == nil {
		t.Fatal("Get succeeded, want failure")
	}
	if got := calls.Load(); got != 3 {
		t.Fatalf("server saw %d calls, want 3 (1 attempt + 2 retries)", got)
	}
}

func TestGetHonoursRetryAfter(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		w.Write([]byte("ok"))
	}))
	defer srv.Close()

	start := time.Now()
	if _, err := fastClient(Options{MaxRetries: 2}).Get(context.Background(), srv.URL); err != nil {
		t.Fatalf("Get: %v", err)
	}
	// The server asked for a second; the 1ms base backoff must not win.
	if elapsed := time.Since(start); elapsed < time.Second {
		t.Fatalf("retried after %s, want >= 1s (server sent Retry-After: 1)", elapsed)
	}
}

func TestGetRespectsCancellation(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()

	c := New(Options{MaxRetries: 10, BaseBackoff: 50 * time.Millisecond, RPS: 1000})
	if _, err := c.Get(ctx, srv.URL); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v, want context.DeadlineExceeded", err)
	}
}

func TestGetObeysRobots(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/robots.txt" {
			w.Write([]byte("User-agent: *\nDisallow: /private/\n"))
			return
		}
		w.Write([]byte("ok"))
	}))
	defer srv.Close()

	c := fastClient(Options{RespectRobots: true})
	if _, err := c.Get(context.Background(), srv.URL+"/public/page"); err != nil {
		t.Fatalf("allowed path: %v", err)
	}
	if _, err := c.Get(context.Background(), srv.URL+"/private/page"); !errors.Is(err, ErrDisallowed) {
		t.Fatalf("err = %v, want ErrDisallowed", err)
	}
}

func TestRobotsIsFetchedOncePerHost(t *testing.T) {
	var robotsHits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/robots.txt" {
			robotsHits.Add(1)
			w.Write([]byte("User-agent: *\nAllow: /\n"))
			return
		}
		w.Write([]byte("ok"))
	}))
	defer srv.Close()

	c := fastClient(Options{RespectRobots: true})
	for range 5 {
		if _, err := c.Get(context.Background(), srv.URL+"/page"); err != nil {
			t.Fatalf("Get: %v", err)
		}
	}
	if got := robotsHits.Load(); got != 1 {
		t.Fatalf("robots.txt fetched %d times, want 1", got)
	}
}
