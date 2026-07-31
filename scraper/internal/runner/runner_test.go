package runner

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/model"
	"marketintel/scraper/internal/source"
)

// fakeSource stands in for a platform adapter and records how many fetches ran
// at the same time.
type fakeSource struct {
	tasks       int
	perTask     int
	failEvery   int           // every Nth task returns an error (0 = never)
	delay       time.Duration // simulated network latency
	inFlight    atomic.Int32
	maxInFlight atomic.Int32
}

func (f *fakeSource) Name() string { return "fake" }

func (f *fakeSource) Discover(_ context.Context, _ *fetch.Client, _ int) ([]source.Task, error) {
	tasks := make([]source.Task, f.tasks)
	for i := range tasks {
		tasks[i] = source.Task{URL: fmt.Sprintf("https://example.test/%d", i), Meta: map[string]string{"i": fmt.Sprint(i)}}
	}
	return tasks, nil
}

func (f *fakeSource) Fetch(ctx context.Context, _ *fetch.Client, t source.Task) ([]model.Product, error) {
	n := f.inFlight.Add(1)
	for {
		peak := f.maxInFlight.Load()
		if n <= peak || f.maxInFlight.CompareAndSwap(peak, n) {
			break
		}
	}
	defer f.inFlight.Add(-1)

	if f.delay > 0 {
		select {
		case <-time.After(f.delay):
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}

	idx := t.Meta["i"]
	if f.failEvery > 0 {
		var i int
		fmt.Sscan(idx, &i)
		if i%f.failEvery == 0 {
			return nil, errors.New("simulated fetch failure")
		}
	}

	out := make([]model.Product, f.perTask)
	for i := range out {
		out[i] = model.Product{
			ID:      fmt.Sprintf("fake:%s-%d", idx, i),
			Source:  "fake",
			Reviews: []model.Review{{ID: "r1"}, {ID: "r2"}},
		}
	}
	return out, nil
}

func collectAll(t *testing.T, src source.Source, opts Options) (Stats, []model.Product, error) {
	t.Helper()
	var (
		mu   sync.Mutex
		got  []model.Product
		emit = func(p model.Product) error {
			mu.Lock()
			defer mu.Unlock()
			got = append(got, p)
			return nil
		}
	)
	stats, err := Run(context.Background(), src, fetch.New(fetch.Options{RPS: 10000}), opts, emit)
	return stats, got, err
}

func TestRunCollectsEverything(t *testing.T) {
	src := &fakeSource{tasks: 10, perTask: 3}

	stats, products, err := collectAll(t, src, Options{Concurrency: 4})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stats.Products != 30 || len(products) != 30 {
		t.Fatalf("Products = %d (emitted %d), want 30", stats.Products, len(products))
	}
	if stats.Reviews != 60 {
		t.Errorf("Reviews = %d, want 60", stats.Reviews)
	}
	if stats.Failed != 0 {
		t.Errorf("Failed = %d, want 0", stats.Failed)
	}
}

func TestRunHonoursConcurrencyLimit(t *testing.T) {
	src := &fakeSource{tasks: 24, perTask: 1, delay: 5 * time.Millisecond}

	if _, _, err := collectAll(t, src, Options{Concurrency: 4}); err != nil {
		t.Fatalf("Run: %v", err)
	}
	peak := src.maxInFlight.Load()
	if peak > 4 {
		t.Fatalf("peak concurrency = %d, want <= 4", peak)
	}
	if peak < 2 {
		t.Fatalf("peak concurrency = %d — the pool is not actually running in parallel", peak)
	}
}

func TestRunSkipsFailedTasksInsteadOfAborting(t *testing.T) {
	src := &fakeSource{tasks: 10, perTask: 1, failEvery: 3} // tasks 0,3,6,9 fail

	var seen atomic.Int32
	stats, products, err := collectAll(t, src, Options{
		Concurrency: 3,
		OnError:     func(source.Task, error) { seen.Add(1) },
	})
	if err != nil {
		t.Fatalf("Run: %v — one bad page must not sink the crawl", err)
	}
	if stats.Failed != 4 {
		t.Errorf("Failed = %d, want 4", stats.Failed)
	}
	if len(products) != 6 {
		t.Errorf("collected %d products, want 6", len(products))
	}
	if seen.Load() != 4 {
		t.Errorf("OnError called %d times, want 4", seen.Load())
	}
}

func TestRunStopsAtLimit(t *testing.T) {
	src := &fakeSource{tasks: 50, perTask: 4, delay: time.Millisecond}

	stats, products, err := collectAll(t, src, Options{Concurrency: 5, Limit: 10})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stats.Products != 10 || len(products) != 10 {
		t.Fatalf("Products = %d (emitted %d), want exactly 10", stats.Products, len(products))
	}
	if stats.Tasks != 50 {
		t.Errorf("Tasks = %d, want 50 discovered even though the crawl stopped early", stats.Tasks)
	}
}

func TestRunPropagatesEmitFailure(t *testing.T) {
	src := &fakeSource{tasks: 5, perTask: 2}
	boom := errors.New("disk full")

	_, err := Run(context.Background(), src, fetch.New(fetch.Options{RPS: 10000}),
		Options{Concurrency: 2}, func(model.Product) error { return boom })

	if !errors.Is(err, boom) {
		t.Fatalf("err = %v, want %v — a broken writer must stop the run", err, boom)
	}
}

func TestRunReportsDiscoveryFailure(t *testing.T) {
	_, err := Run(context.Background(), failingDiscovery{}, fetch.New(fetch.Options{RPS: 10000}),
		Options{}, func(model.Product) error { return nil })

	if err == nil {
		t.Fatal("Run succeeded, want the discovery error surfaced")
	}
}

type failingDiscovery struct{}

func (failingDiscovery) Name() string { return "broken" }
func (failingDiscovery) Discover(context.Context, *fetch.Client, int) ([]source.Task, error) {
	return nil, errors.New("host unreachable")
}
func (failingDiscovery) Fetch(context.Context, *fetch.Client, source.Task) ([]model.Product, error) {
	return nil, nil
}
