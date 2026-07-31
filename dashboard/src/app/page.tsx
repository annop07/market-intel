"use client";

import { useEffect, useState } from "react";

import { AskBox } from "@/components/ask-box";
import {
  AspectSentimentChart,
  BrandPriceChart,
  PriceTrendChart,
} from "@/components/charts";
import { Empty, Panel, Skeleton } from "@/components/panel";
import {
  getCategories,
  getChanges,
  getHealth,
  getHistory,
  getLatestReport,
  getPricing,
} from "@/lib/api";
import { LANGUAGES, dict, useLang } from "@/lib/i18n";
import type {
  Category,
  ExecutiveReport,
  Health,
  History,
  MarketChanges,
  PriceIntelligence,
} from "@/lib/types";

export default function Dashboard() {
  const [lang, setLang] = useLang();
  const t = dict(lang);

  const [health, setHealth] = useState<Health | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [category, setCategory] = useState<string>("");
  const [pricing, setPricing] = useState<PriceIntelligence | null>(null);
  const [changes, setChanges] = useState<MarketChanges | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [report, setReport] = useState<ExecutiveReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Loading is derived, not stored: the panels are stale exactly when the data
  // on screen was fetched for a different category or language.
  const requestKey = `${category}|${lang}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = !category || loadedKey !== requestKey;

  useEffect(() => {
    (async () => {
      try {
        const [h, cats] = await Promise.all([getHealth(), getCategories()]);
        setHealth(h);
        setCategories(cats);
        setCategory((current) => current || cats[0]?.category || "");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  // Each language has its own report archive, so switching reloads the report
  // rather than showing English prose under a Thai heading.
  //
  // `active` drops responses for a language the reader has already switched
  // away from: the first render is always "en" (the server snapshot), so a
  // stored Thai preference fires both requests and the slower one would
  // otherwise win.
  useEffect(() => {
    let active = true;
    getLatestReport(lang)
      .then((latest) => {
        if (!active) return;
        setReport(latest);
        // Land on the category the last report covered — that is the one with
        // sentiment data behind it.
        if (latest?.category) setCategory(latest.category);
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      active = false;
    };
  }, [lang]);

  useEffect(() => {
    if (!category) return;
    let active = true;

    // allSettled, not all: one endpoint failing should blank its own panel,
    // not the entire page.
    Promise.allSettled([
      getPricing(category, lang),
      getChanges(category, lang),
      getHistory(category),
    ]).then(([price, moved, series]) => {
      if (!active) return;
      setPricing(price.status === "fulfilled" ? price.value : null);
      setChanges(moved.status === "fulfilled" ? moved.value : null);
      setHistory(series.status === "fulfilled" ? series.value : null);

      const failure = [price, moved, series].find((r) => r.status === "rejected");
      setError(failure ? String((failure as PromiseRejectedResult).reason) : null);
      setLoadedKey(requestKey);
    });

    return () => {
      active = false;
    };
  }, [category, lang, requestKey]);

  const dist = pricing?.distribution ?? {};
  const showSentiment = report?.category === category;
  const medianDelta = changes?.has_history ? changes.median_change_pct : null;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-3 px-6 py-3">
          <div className="mr-auto">
            <h1 className="text-lg leading-none font-normal tracking-tight">
              {t.title}
            </h1>
            <p className="eyebrow mt-1.5">
              {health
                ? t.stats(
                    health.products,
                    health.reviews,
                    health.vectors,
                    health.sources.length,
                  )
                : t.connecting}
            </p>
          </div>

          <label className="flex items-center gap-2">
            <span className="eyebrow">{t.category}</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="border border-line bg-transparent px-2.5 py-1.5 font-mono text-xs text-ink"
            >
              {categories.map((c) => (
                <option key={c.category} value={c.category}>
                  {c.category} ({c.products})
                </option>
              ))}
            </select>
          </label>

          <div className="flex border border-line" role="group" aria-label="language">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                onClick={() => setLang(l.code)}
                aria-pressed={lang === l.code}
                className={`px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] uppercase transition-colors duration-300 ${
                  lang === l.code
                    ? "bg-accent text-accent-ink"
                    : "text-subtle hover:text-ink"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] space-y-4 px-6 py-6">
        {error && (
          <p
            role="alert"
            className="border border-negative/40 px-4 py-3 text-sm text-negative"
          >
            {error} {t.apiDown(process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001")}
          </p>
        )}

        {report ? (
          <section className="panel border-l-2 border-l-accent p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <span className="eyebrow">
                {t.latestReport} · {report.category ?? t.allCategories}
              </span>
              <span className="eyebrow">
                {new Date(report.generated_at).toLocaleDateString()} ·{" "}
                {report.usage?.total_tokens ?? 0} {t.tokens}
              </span>
            </div>
            <p className="mt-4 max-w-4xl text-xl leading-snug font-light tracking-tight">
              {report.headline}
            </p>
            <p className="text-muted mt-3 max-w-3xl text-sm leading-relaxed">
              {report.summary}
            </p>
            <p className="eyebrow mt-4">
              {t.reportMeta(
                report.sentiment.mentions_kept,
                report.sentiment.mentions_discarded,
                report.citations_dropped,
              )}
            </p>
          </section>
        ) : (
          <p className="border border-dashed border-line px-4 py-3 text-sm text-subtle">
            {t.noReportForLang}
          </p>
        )}

        <section className="grid grid-cols-2 divide-x divide-line border border-line sm:grid-cols-4">
          <Stat label={t.products} value={dist.count ?? 0} loading={loading} />
          <Stat label={t.brands} value={pricing?.brands.length ?? 0} loading={loading} />
          <Stat
            label={t.medianPrice}
            value={dist.median != null ? dist.median.toFixed(2) : "—"}
            hint={dist.currency}
            delta={medianDelta}
            loading={loading}
          />
          <Stat
            label={t.priceSpread}
            value={
              dist.min != null && dist.max != null
                ? `${dist.min.toFixed(0)}–${dist.max.toFixed(0)}`
                : "—"
            }
            hint={dist.p90 != null ? `p90 ${dist.p90.toFixed(0)}` : undefined}
            loading={loading}
          />
        </section>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title={t.brandPrices} hint={t.brandPricesHint} loading={loading}>
            {pricing?.brands.length ? (
              <BrandPriceChart brands={pricing.brands} t={t} />
            ) : (
              <Empty>{t.emptyNoProducts}</Empty>
            )}
          </Panel>

          <Panel
            title={t.aspectsTitle}
            hint={
              showSentiment
                ? t.aspectsHint
                : report
                  ? t.aspectsOtherCategory(report.category ?? "—")
                  : t.noReportForLang
            }
          >
            {showSentiment && report ? (
              <AspectSentimentChart aspects={report.sentiment.aspects} t={t} />
            ) : (
              <Empty>{t.emptyRunReport(category)}</Empty>
            )}
          </Panel>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Panel
            title={t.trend}
            hint={history ? t.trendHint(history.days_observed) : undefined}
            loading={loading}
          >
            {history && history.series.length > 1 ? (
              <PriceTrendChart series={history.series} t={t} />
            ) : (
              <Empty>{t.noHistory}</Empty>
            )}
          </Panel>

          <Panel
            title={t.changes}
            hint={
              changes?.has_history && changes.baseline_day && changes.latest_day
                ? t.changesHint(changes.baseline_day, changes.latest_day)
                : undefined
            }
            loading={loading}
          >
            {changes?.has_history ? (
              <div className="space-y-5">
                <ul className="space-y-1.5 text-sm">
                  {changes.observations.map((o) => (
                    <li key={o} className="flex gap-2.5">
                      <span className="text-accent">—</span>
                      <span className="text-muted">{o}</span>
                    </li>
                  ))}
                </ul>

                {changes.price_moves.length > 0 && (
                  <div>
                    <p className="eyebrow mb-2">{t.movers}</p>
                    <ul className="divide-y divide-line border-y border-line">
                      {changes.price_moves.slice(0, 6).map((m) => (
                        <li
                          key={m.product_id}
                          className="flex items-baseline gap-3 py-1.5 text-sm"
                        >
                          <span
                            className={`w-16 shrink-0 font-mono text-xs ${
                              m.direction === "down" ? "text-positive" : "text-warn"
                            }`}
                          >
                            {m.direction === "down" ? "↓" : "↑"}{" "}
                            {Math.abs(m.change_pct).toFixed(1)}%
                          </span>
                          <span className="truncate">{m.title}</span>
                          <span className="text-subtle ml-auto shrink-0 font-mono text-xs">
                            {m.from_price.toFixed(2)} → {m.to_price.toFixed(2)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  <Tag
                    label={t.wentOut}
                    count={changes.stock_flips.filter((f) => !f.in_stock).length}
                    tone="warn"
                  />
                  <Tag
                    label={t.cameBack}
                    count={changes.stock_flips.filter((f) => f.in_stock).length}
                    tone="positive"
                  />
                  <Tag label={t.newListings} count={changes.new_products.length} />
                  <Tag label={t.gone} count={changes.disappeared.length} />
                </div>
              </div>
            ) : (
              <Empty>{t.noHistory}</Empty>
            )}
          </Panel>
        </div>

        {pricing?.observations.length ? (
          <Panel title={t.findings} hint={t.findingsHint}>
            <ul className="grid gap-2 text-sm lg:grid-cols-2">
              {pricing.observations.map((o) => (
                <li key={o} className="flex gap-2.5">
                  <span className="text-accent">—</span>
                  <span className="text-muted">{o}</span>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {pricing?.brands.length ? (
          <Panel title={t.competitors} padded={false}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line">
                    <Th>{t.colBrand}</Th>
                    <Th align="right">{t.colProducts}</Th>
                    <Th align="right">{t.colAvgPrice}</Th>
                    <Th align="right">{t.colIndex}</Th>
                    <Th align="right">{t.colRating}</Th>
                    <Th align="right">{t.colInStock}</Th>
                    <Th align="right">{t.colDiscount}</Th>
                  </tr>
                </thead>
                <tbody>
                  {pricing.brands.map((b) => {
                    const index = b.price_index ?? 100;
                    return (
                      <tr
                        key={b.brand}
                        className="border-b border-line/60 transition-colors duration-200 last:border-0 hover:bg-inset"
                      >
                        <td className="px-4 py-2.5 font-medium">{b.brand}</td>
                        <Td>{b.products}</Td>
                        <Td>{b.avg_price.toFixed(2)}</Td>
                        <td className="px-4 py-2.5 text-right">
                          <span className="inline-flex items-center gap-2">
                            {/* A bar against the 100 = median line reads faster
                                than the number alone, and does not rely on colour. */}
                            <span className="relative hidden h-1 w-16 bg-inset sm:inline-block">
                              <span
                                className={index >= 100 ? "bg-warn" : "bg-positive"}
                                style={{
                                  position: "absolute",
                                  top: 0,
                                  bottom: 0,
                                  left: index >= 100 ? "50%" : `${Math.max(0, 50 - (100 - index) / 4)}%`,
                                  width: `${Math.min(50, Math.abs(index - 100) / 4)}%`,
                                }}
                              />
                              <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                            </span>
                            <span className="font-mono text-xs">{index.toFixed(0)}</span>
                          </span>
                        </td>
                        <Td>{b.avg_rating?.toFixed(2) ?? "—"}</Td>
                        <Td>{b.in_stock_pct != null ? `${b.in_stock_pct.toFixed(0)}%` : "—"}</Td>
                        <Td>
                          {b.avg_discount_pct != null ? `${b.avg_discount_pct.toFixed(1)}%` : "—"}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        ) : null}

        {pricing?.gaps.length ? (
          <Panel title={t.gaps} hint={t.gapsHint}>
            <ul className="divide-y divide-line border-y border-line">
              {pricing.gaps.map((g) => (
                <li
                  key={`${g.lower_price}-${g.upper_price}`}
                  className="flex flex-wrap items-baseline gap-x-3 py-2 text-sm"
                >
                  <span className="font-mono">
                    {g.lower_price.toFixed(2)} → {g.upper_price.toFixed(2)}
                  </span>
                  <span className="font-mono text-xs text-accent">
                    +{g.gap_pct.toFixed(0)}%
                  </span>
                  <span className="text-subtle text-xs">
                    {t.gapBetween(g.below, g.above)}
                  </span>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        <AskBox category={category || undefined} lang={lang} t={t} />

        {report?.recommendations.length ? (
          <Panel title={t.recommendations} hint={t.recommendationsHint}>
            <ul className="space-y-4 text-sm">
              {report.recommendations.map((r) => (
                <li key={r.action} className="border-l-2 border-line pl-4">
                  <span
                    className={`eyebrow ${r.priority === "high" ? "text-negative" : ""}`}
                  >
                    {r.priority}
                  </span>
                  <p className="mt-1 font-medium">{r.action}</p>
                  <p className="text-muted mt-1">{r.rationale}</p>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        <footer className="eyebrow border-t border-line pt-4 leading-relaxed">
          {t.footer(health?.llm_model ?? "—")}
        </footer>
      </main>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  delta,
  loading,
}: {
  label: string;
  value: string | number;
  hint?: string;
  delta?: number | null;
  loading?: boolean;
}) {
  return (
    <div className="p-4">
      <p className="eyebrow">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-24" />
      ) : (
        <p className="mt-1.5 text-2xl font-light tracking-tight tabular-nums">{value}</p>
      )}
      <p className="eyebrow mt-1 flex items-center gap-2">
        {hint}
        {delta != null && Math.abs(delta) >= 0.5 && (
          <span className={delta < 0 ? "text-positive" : "text-warn"}>
            {delta < 0 ? "↓" : "↑"} {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </p>
    </div>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th className={`eyebrow px-4 py-2.5 ${align === "right" ? "text-right" : "text-left"}`}>
      {children}
    </th>
  );
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-2.5 text-right font-mono text-xs">{children}</td>;
}

/** A count worth glancing at — hidden entirely when it is zero. */
function Tag({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone?: "positive" | "warn";
}) {
  if (!count) return null;
  const colour =
    tone === "warn"
      ? "border-warn/40 text-warn"
      : tone === "positive"
        ? "border-positive/40 text-positive"
        : "border-line text-subtle";
  return (
    <span className={`border px-2.5 py-1 font-mono text-[11px] ${colour}`}>
      {count} {label}
    </span>
  );
}
