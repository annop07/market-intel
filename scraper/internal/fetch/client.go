// Package fetch is the polite HTTP layer shared by every source adapter:
// one global rate limit per host, bounded retries with exponential backoff,
// per-request context deadlines, and robots.txt enforcement.
package fetch

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net/http"
	"strconv"
	"time"

	"github.com/PuerkitoBio/goquery"
	"golang.org/x/time/rate"
)

// Options configures a Client. The zero value is not useful; use Defaults.
type Options struct {
	RPS           float64       // requests per second, per client
	Burst         int           // bucket size for short spikes
	MaxRetries    int           // retries after the first attempt
	BaseBackoff   time.Duration // first backoff; doubles each retry
	Timeout       time.Duration // per-attempt timeout
	UserAgent     string
	RespectRobots bool
}

// Defaults are deliberately conservative: this collector is a good citizen by
// default and has to be explicitly told to go faster.
func Defaults() Options {
	return Options{
		RPS:           2,
		Burst:         4,
		MaxRetries:    3,
		BaseBackoff:   500 * time.Millisecond,
		Timeout:       15 * time.Second,
		UserAgent:     "market-intel-bot/0.1 (+https://github.com/; portfolio project; contact via repo issues)",
		RespectRobots: true,
	}
}

// ErrDisallowed is returned when robots.txt forbids the URL for our user agent.
var ErrDisallowed = errors.New("fetch: disallowed by robots.txt")

// StatusError carries a non-retryable HTTP status back to the caller.
type StatusError struct {
	Code int
	URL  string
}

func (e *StatusError) Error() string {
	return fmt.Sprintf("fetch: %s returned %d %s", e.URL, e.Code, http.StatusText(e.Code))
}

// Client is safe for concurrent use by multiple workers.
type Client struct {
	http   *http.Client
	lim    *rate.Limiter
	robots *robotsCache
	opts   Options
}

// New builds a Client from opts, filling in zero fields from Defaults.
func New(opts Options) *Client {
	d := Defaults()
	if opts.RPS <= 0 {
		opts.RPS = d.RPS
	}
	if opts.Burst <= 0 {
		opts.Burst = d.Burst
	}
	if opts.MaxRetries <= 0 {
		opts.MaxRetries = d.MaxRetries
	}
	if opts.BaseBackoff <= 0 {
		opts.BaseBackoff = d.BaseBackoff
	}
	if opts.Timeout <= 0 {
		opts.Timeout = d.Timeout
	}
	if opts.UserAgent == "" {
		opts.UserAgent = d.UserAgent
	}
	c := &Client{
		http: &http.Client{Timeout: opts.Timeout},
		lim:  rate.NewLimiter(rate.Limit(opts.RPS), opts.Burst),
		opts: opts,
	}
	c.robots = newRobotsCache(c.rawGet, opts.UserAgent)
	return c
}

// Get returns the response body, retrying transient failures.
//
// Retryable: connection errors, 429, and 5xx. Everything else (404, 403, …)
// fails immediately — retrying a deterministic rejection only wastes the
// server's time and ours.
func (c *Client) Get(ctx context.Context, url string) ([]byte, error) {
	if c.opts.RespectRobots {
		ok, err := c.robots.allowed(ctx, url)
		if err != nil {
			return nil, err
		}
		if !ok {
			return nil, fmt.Errorf("%w: %s", ErrDisallowed, url)
		}
	}

	var lastErr error
	for attempt := 0; attempt <= c.opts.MaxRetries; attempt++ {
		if attempt > 0 {
			if err := sleep(ctx, c.backoff(attempt, lastErr)); err != nil {
				return nil, err
			}
		}
		if err := c.lim.Wait(ctx); err != nil {
			return nil, err
		}

		body, err := c.rawGet(ctx, url)
		if err == nil {
			return body, nil
		}
		lastErr = err

		var se *StatusError
		if errors.As(err, &se) && !retryableStatus(se.Code) {
			return nil, err
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
	}
	return nil, fmt.Errorf("fetch: giving up on %s after %d attempts: %w", url, c.opts.MaxRetries+1, lastErr)
}

// JSON fetches url and decodes the body into v.
func (c *Client) JSON(ctx context.Context, url string, v any) error {
	body, err := c.Get(ctx, url)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(body, v); err != nil {
		return fmt.Errorf("fetch: decoding %s: %w", url, err)
	}
	return nil
}

// Doc fetches url and parses it as HTML.
func (c *Client) Doc(ctx context.Context, url string) (*goquery.Document, error) {
	body, err := c.Get(ctx, url)
	if err != nil {
		return nil, err
	}
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("fetch: parsing %s: %w", url, err)
	}
	return doc, nil
}

// rawGet performs exactly one attempt with no retry and no rate limiting.
// The robots cache uses it directly to avoid recursing into Get.
func (c *Client) rawGet(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	// Note: no manual Accept-Encoding — setting it yourself turns off net/http's
	// transparent gzip decompression and you get compressed bytes back.
	req.Header.Set("User-Agent", c.opts.UserAgent)

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		// Drain a little so the connection can be reused.
		_, _ = io.CopyN(io.Discard, resp.Body, 4<<10)
		err := &StatusError{Code: resp.StatusCode, URL: url}
		if ra := retryAfter(resp); ra > 0 {
			return nil, &throttled{StatusError: err, after: ra}
		}
		return nil, err
	}
	return io.ReadAll(io.LimitReader(resp.Body, 8<<20))
}

// throttled is a StatusError that also carries the server's Retry-After hint.
type throttled struct {
	*StatusError
	after time.Duration
}

func (c *Client) backoff(attempt int, lastErr error) time.Duration {
	var t *throttled
	if errors.As(lastErr, &t) && t.after > 0 {
		return t.after // the server told us how long to wait; obey it
	}
	d := c.opts.BaseBackoff << (attempt - 1)
	// Full jitter: spreads a fleet of workers that all failed at the same time.
	return time.Duration(rand.Int64N(int64(d)) + int64(d)/2)
}

func retryableStatus(code int) bool {
	return code == http.StatusTooManyRequests || code >= 500
}

func retryAfter(resp *http.Response) time.Duration {
	v := resp.Header.Get("Retry-After")
	if v == "" {
		return 0
	}
	if secs, err := strconv.Atoi(v); err == nil {
		return time.Duration(secs) * time.Second
	}
	if t, err := http.ParseTime(v); err == nil {
		if d := time.Until(t); d > 0 {
			return d
		}
	}
	return 0
}

func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
