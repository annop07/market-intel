package fetch

import (
	"context"
	"errors"
	"net/url"
	"strings"
	"sync"
)

// robotsCache fetches and caches one robots.txt per host, so a crawl of 1000
// pages costs exactly one extra request per host.
//
// It implements the subset of the Robots Exclusion Protocol that matters here:
// User-agent groups, Allow, Disallow, and longest-match-wins between the two.
// Anything it cannot parse is treated as "allowed" — same as a missing file.
type robotsCache struct {
	get   func(context.Context, string) ([]byte, error)
	agent string

	mu    sync.Mutex
	hosts map[string]*robots
}

func newRobotsCache(get func(context.Context, string) ([]byte, error), userAgent string) *robotsCache {
	token := strings.ToLower(userAgent)
	if i := strings.IndexAny(token, "/ "); i > 0 {
		token = token[:i] // "market-intel-bot/0.1 (…)" -> "market-intel-bot"
	}
	return &robotsCache{get: get, agent: token, hosts: map[string]*robots{}}
}

func (c *robotsCache) allowed(ctx context.Context, rawURL string) (bool, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return false, err
	}
	key := u.Scheme + "://" + u.Host

	c.mu.Lock()
	r, ok := c.hosts[key]
	c.mu.Unlock()

	if !ok {
		body, err := c.get(ctx, key+"/robots.txt")
		if err != nil {
			var se *StatusError
			// No robots.txt (or the host is unhappy) means no restrictions.
			// A cancelled context is a real error and must not be swallowed.
			if ctx.Err() != nil {
				return false, ctx.Err()
			}
			if !errors.As(err, &se) {
				return true, nil
			}
			body = nil
		}
		r = parseRobots(body, c.agent)
		c.mu.Lock()
		c.hosts[key] = r
		c.mu.Unlock()
	}
	return r.allows(u.EscapedPath()), nil
}

type robots struct {
	allow    []string
	disallow []string
}

// parseRobots keeps the rules of the most specific group that applies to us:
// a group naming our token wins over the wildcard group.
func parseRobots(body []byte, agent string) *robots {
	r := &robots{}
	if len(body) == 0 {
		return r
	}

	var (
		current      []string // agents named by the group being read
		inGroup      bool
		exactRules   *robots
		starRules    = &robots{}
		lastWasAgent bool
	)
	target := &robots{}

	flush := func() {
		if !inGroup {
			return
		}
		for _, a := range current {
			switch a {
			case agent:
				exactRules = cloneRules(target)
			case "*":
				starRules = cloneRules(target)
			}
		}
		target = &robots{}
	}

	for _, line := range strings.Split(string(body), "\n") {
		if i := strings.IndexByte(line, '#'); i >= 0 {
			line = line[:i]
		}
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		key = strings.ToLower(strings.TrimSpace(key))
		value = strings.TrimSpace(value)

		switch key {
		case "user-agent":
			if !lastWasAgent {
				flush()
				current = nil
			}
			current = append(current, strings.ToLower(value))
			inGroup, lastWasAgent = true, true
		case "allow":
			if value != "" {
				target.allow = append(target.allow, value)
			}
			lastWasAgent = false
		case "disallow":
			target.disallow = append(target.disallow, value)
			lastWasAgent = false
		default:
			lastWasAgent = false
		}
	}
	flush()

	if exactRules != nil {
		return exactRules
	}
	return starRules
}

func cloneRules(r *robots) *robots {
	return &robots{allow: append([]string(nil), r.allow...), disallow: append([]string(nil), r.disallow...)}
}

// allows applies longest-match-wins: the more specific rule decides, and a tie
// resolves to Allow (the convention every major crawler follows).
func (r *robots) allows(path string) bool {
	if path == "" {
		path = "/"
	}
	longestAllow, longestDisallow := -1, -1
	for _, p := range r.allow {
		if matchPrefix(path, p) && len(p) > longestAllow {
			longestAllow = len(p)
		}
	}
	for _, p := range r.disallow {
		if p == "" {
			continue // "Disallow:" with no value means allow everything
		}
		if matchPrefix(path, p) && len(p) > longestDisallow {
			longestDisallow = len(p)
		}
	}
	return longestDisallow < 0 || longestAllow >= longestDisallow
}

// matchPrefix supports the two wildcards in common use: "*" for any run of
// characters and a trailing "$" anchoring the end of the path.
func matchPrefix(path, pattern string) bool {
	anchored := strings.HasSuffix(pattern, "$")
	pattern = strings.TrimSuffix(pattern, "$")

	parts := strings.Split(pattern, "*")
	pos := 0
	for i, part := range parts {
		if part == "" {
			continue
		}
		var idx int
		if i == 0 {
			if !strings.HasPrefix(path[pos:], part) {
				return false
			}
			idx = 0
		} else {
			idx = strings.Index(path[pos:], part)
			if idx < 0 {
				return false
			}
		}
		pos += idx + len(part)
	}
	if anchored {
		return pos == len(path)
	}
	return true
}
