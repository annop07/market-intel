// Thin typed client for the market-intel API.
import type {
  AskResponse,
  Category,
  ExecutiveReport,
  Health,
  History,
  MarketChanges,
  PriceIntelligence,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${detail.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<Health> {
  return json(await fetch(`${BASE}/health`, { cache: "no-store" }));
}

export async function getCategories(): Promise<Category[]> {
  const data = await json<{ categories: Category[] }>(
    await fetch(`${BASE}/catalogue?limit=1`, { cache: "no-store" }),
  );
  return data.categories;
}

export async function getPricing(
  category?: string,
  language = "en",
): Promise<PriceIntelligence> {
  const params = new URLSearchParams({ language });
  if (category) params.set("category", category);
  return json(await fetch(`${BASE}/analyze/pricing?${params}`, { cache: "no-store" }));
}

/** What moved since the crawl closest to `days` ago. Deterministic, so free to poll. */
export async function getChanges(
  category?: string,
  language = "en",
  days = 7,
): Promise<MarketChanges> {
  const params = new URLSearchParams({ language, days: String(days) });
  if (category) params.set("category", category);
  return json(await fetch(`${BASE}/analyze/changes?${params}`, { cache: "no-store" }));
}

export async function getHistory(category?: string, days = 30): Promise<History> {
  const params = new URLSearchParams({ days: String(days) });
  if (category) params.set("category", category);
  return json(await fetch(`${BASE}/analyze/history?${params}`, { cache: "no-store" }));
}

/**
 * The last report that was actually generated, in the requested language.
 * Reading the saved artefact keeps the dashboard free to open — running a fresh
 * report costs tokens, so that stays an explicit action (the CLI or POST /report).
 *
 * Returns null when nothing has been generated in that language yet; the caller
 * shows a hint rather than falling back to the other language, which would look
 * like a failed translation.
 */
export async function getLatestReport(language = "en"): Promise<ExecutiveReport | null> {
  const res = await fetch(`${BASE}/report/latest.json?language=${language}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  return json(res);
}

export async function ask(
  question: string,
  category?: string,
  language = "en",
): Promise<AskResponse> {
  return json(
    await fetch(`${BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, language, ...(category ? { category } : {}) }),
    }),
  );
}
