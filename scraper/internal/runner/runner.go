// Package runner drives a Source across a bounded worker pool.
//
// This is the piece that justifies writing the collector in Go: discovery is
// sequential and cheap, detail fetching is the slow part, and the pool keeps
// exactly N requests in flight while the rate limiter inside fetch.Client caps
// how fast those N are allowed to fire.
package runner

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/model"
	"marketintel/scraper/internal/source"
)

// Options controls one collection run.
type Options struct {
	Concurrency int // workers in flight; <=0 means 4
	Limit       int // stop after this many products; <=0 means no cap
	OnError     func(task source.Task, err error)
	OnProgress  func(products int)
}

// Stats summarises a finished run.
type Stats struct {
	Tasks    int
	Products int
	Reviews  int
	Failed   int
	Elapsed  time.Duration
}

func (s Stats) String() string {
	return fmt.Sprintf("%d products (%d reviews) from %d tasks in %s, %d failed",
		s.Products, s.Reviews, s.Tasks, s.Elapsed.Round(time.Millisecond), s.Failed)
}

// Emit receives every collected product. It is called from a single goroutine,
// so implementations do not need their own locking.
type Emit func(model.Product) error

// Run discovers work for src and fetches it with a worker pool.
//
// A task that fails after its retries is counted and skipped — one dead product
// page must not sink a 1000-page crawl. Only a failure to discover any work at
// all, or a caller-side emit error, aborts the run.
func Run(ctx context.Context, src source.Source, c *fetch.Client, opts Options, emit Emit) (Stats, error) {
	start := time.Now()
	stats := Stats{}

	workers := opts.Concurrency
	if workers <= 0 {
		workers = 4
	}

	tasks, err := src.Discover(ctx, c, opts.Limit)
	if err != nil {
		return stats, fmt.Errorf("discover %s: %w", src.Name(), err)
	}
	stats.Tasks = len(tasks)
	if len(tasks) == 0 {
		return stats, nil
	}

	var (
		taskCh  = make(chan source.Task)
		results = make(chan []model.Product)
		wg      sync.WaitGroup
	)

	// Cancelled as soon as the collector hits its product limit or the emitter
	// fails, so in-flight workers stop instead of finishing a doomed crawl.
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	go func() {
		defer close(taskCh)
		for _, t := range tasks {
			select {
			case taskCh <- t:
			case <-ctx.Done():
				return
			}
		}
	}()

	for range workers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for t := range taskCh {
				products, err := src.Fetch(ctx, c, t)
				if err != nil {
					if ctx.Err() != nil {
						return
					}
					if opts.OnError != nil {
						opts.OnError(t, err)
					}
					select {
					case results <- nil:
					case <-ctx.Done():
						return
					}
					continue
				}
				select {
				case results <- products:
				case <-ctx.Done():
					return
				}
			}
		}()
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	var emitErr error
	for batch := range results {
		if batch == nil {
			stats.Failed++
			continue
		}
		for _, p := range batch {
			if opts.Limit > 0 && stats.Products >= opts.Limit {
				cancel()
				break
			}
			if err := emit(p); err != nil {
				emitErr = err
				cancel()
				break
			}
			stats.Products++
			stats.Reviews += len(p.Reviews)
			if opts.OnProgress != nil {
				opts.OnProgress(stats.Products)
			}
		}
		if emitErr != nil || (opts.Limit > 0 && stats.Products >= opts.Limit) {
			cancel()
		}
	}

	stats.Elapsed = time.Since(start)
	if emitErr != nil {
		return stats, emitErr
	}
	// Hitting the limit cancels the context on purpose — that is success, not failure.
	if err := ctx.Err(); err != nil && errors.Is(err, context.Canceled) && stats.Products > 0 {
		return stats, nil
	}
	return stats, nil
}
