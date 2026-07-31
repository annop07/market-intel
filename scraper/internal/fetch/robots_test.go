package fetch

import "testing"

func TestParseRobotsGroups(t *testing.T) {
	body := []byte(`
# a comment
User-agent: *
Disallow: /test-sites/e-commerce/
Allow: /test-sites/e-commerce/public/

User-agent: BadBot
Disallow: /
`)
	r := parseRobots(body, "market-intel-bot")

	cases := []struct {
		path string
		want bool
	}{
		{"/", true},
		{"/test-sites/tables", true},
		{"/test-sites/e-commerce/allinone", false},
		{"/test-sites/e-commerce/public/list", true}, // longer Allow wins
	}
	for _, c := range cases {
		if got := r.allows(c.path); got != c.want {
			t.Errorf("allows(%q) = %v, want %v", c.path, got, c.want)
		}
	}
}

func TestParseRobotsPrefersOurGroupOverWildcard(t *testing.T) {
	body := []byte(`
User-agent: *
Disallow: /

User-agent: market-intel-bot
Disallow: /admin/
`)
	r := parseRobots(body, "market-intel-bot")

	if !r.allows("/products/1") {
		t.Error("a group naming our agent must override the wildcard group")
	}
	if r.allows("/admin/panel") {
		t.Error("/admin/ is disallowed for our agent")
	}
}

func TestParseRobotsStackedAgentsShareOneGroup(t *testing.T) {
	body := []byte(`
User-agent: market-intel-bot
User-agent: some-other-bot
Disallow: /nope/
`)
	r := parseRobots(body, "market-intel-bot")

	if r.allows("/nope/x") {
		t.Error("consecutive User-agent lines form one group; the rules apply to all of them")
	}
	if !r.allows("/yes/x") {
		t.Error("unrelated paths stay allowed")
	}
}

func TestParseRobotsEmptyDisallowMeansAllowAll(t *testing.T) {
	r := parseRobots([]byte("User-agent: *\nDisallow:\n"), "market-intel-bot")
	if !r.allows("/anything") {
		t.Error("an empty Disallow value grants full access")
	}
}

func TestParseRobotsMissingFileAllowsEverything(t *testing.T) {
	if !parseRobots(nil, "market-intel-bot").allows("/anything") {
		t.Error("no robots.txt means no restrictions")
	}
}

func TestMatchPrefixWildcards(t *testing.T) {
	cases := []struct {
		path, pattern string
		want          bool
	}{
		{"/shop/?add-to-cart=759", "/*?add-to-cart=", true},
		{"/shop/item", "/*?add-to-cart=", false},
		{"/a/b/c.php", "/*.php$", true},
		{"/a/b/c.php?x=1", "/*.php$", false}, // $ anchors the end
		{"/wp-admin/admin-ajax.php", "/wp-admin/", true},
	}
	for _, c := range cases {
		if got := matchPrefix(c.path, c.pattern); got != c.want {
			t.Errorf("matchPrefix(%q, %q) = %v, want %v", c.path, c.pattern, got, c.want)
		}
	}
}
