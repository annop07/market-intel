// Command collect gathers competitor products and reviews from one or more
// sources and writes them as JSONL and/or posts them to the analysis API.
//
//	collect -source dummyjson -limit 100 -out ../data/raw/dummyjson.jsonl
//	collect -source all -api http://localhost:8001/ingest
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"marketintel/scraper/internal/fetch"
	"marketintel/scraper/internal/runner"
	"marketintel/scraper/internal/source"
	"marketintel/scraper/internal/store"
)

func main() {
	var (
		sources     = flag.String("source", "dummyjson", `comma-separated source names, or "all"`)
		limit       = flag.Int("limit", 0, "stop after N products per source (0 = no limit)")
		out         = flag.String("out", "", "JSONL output path (default data/raw/<source>-<date>.jsonl)")
		api         = flag.String("api", "", "also POST products to this /ingest endpoint")
		concurrency = flag.Int("concurrency", 4, "workers fetching in parallel")
		rps         = flag.Float64("rps", 2, "max requests per second per source")
		timeout     = flag.Duration("timeout", 10*time.Minute, "overall deadline for the run")
		noRobots    = flag.Bool("ignore-robots", false, "skip robots.txt checks (don't)")
		list        = flag.Bool("list", false, "list available sources and exit")
	)
	flag.Parse()

	if *list {
		for _, s := range source.All() {
			fmt.Println(s.Name())
		}
		return
	}

	names := source.Names()
	if *sources != "all" {
		names = strings.Split(*sources, ",")
	}

	// Ctrl-C cancels the run; writers still flush what they already have.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, *timeout)
	defer cancel()

	total := 0
	for _, name := range names {
		name = strings.TrimSpace(name)
		if name == "" {
			continue
		}
		n, err := collect(ctx, name, *out, *api, *limit, *concurrency, *rps, !*noRobots)
		if err != nil {
			log.Printf("✗ %s: %v", name, err)
			continue
		}
		total += n
	}
	if total == 0 {
		os.Exit(1)
	}
}

func collect(ctx context.Context, name, out, api string, limit, concurrency int, rps float64, robots bool) (int, error) {
	src, err := source.Get(name)
	if err != nil {
		return 0, err
	}

	path := out
	if path == "" {
		path = fmt.Sprintf("data/raw/%s-%s.jsonl", name, time.Now().UTC().Format("2006-01-02"))
	} else if len(name) > 0 && strings.Contains(out, "{source}") {
		path = strings.ReplaceAll(out, "{source}", name)
	}

	jsonl, err := store.NewJSONL(path)
	if err != nil {
		return 0, err
	}
	writers := store.Multi{jsonl}
	if api != "" {
		writers = append(writers, store.NewAPI(api, 50))
	}
	defer func() {
		if err := writers.Close(); err != nil {
			log.Printf("✗ %s: flushing output: %v", name, err)
		}
	}()

	client := fetch.New(fetch.Options{
		RPS:           rps,
		Burst:         concurrency,
		RespectRobots: robots,
	})

	log.Printf("▶ %s: collecting (concurrency=%d, rps=%.1f)…", name, concurrency, rps)
	stats, err := runner.Run(ctx, src, client, runner.Options{
		Concurrency: concurrency,
		Limit:       limit,
		OnError: func(t source.Task, err error) {
			log.Printf("  ! %s: %v", t.URL, err)
		},
	}, writers.Write)
	if err != nil {
		return stats.Products, err
	}

	log.Printf("✓ %s: %s → %s", name, stats, path)
	return stats.Products, nil
}
