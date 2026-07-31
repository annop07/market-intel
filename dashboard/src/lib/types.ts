// Mirrors the Pydantic models in api/app — see contract.py, pricing.py, report.py.

export type Health = {
  status: string;
  llm_configured: boolean;
  llm_model: string;
  products: number;
  reviews: number;
  vectors: number;
  sources: { source: string; products: number; reviews: number }[];
};

export type Category = {
  category: string;
  products: number;
  brands: number;
  avg_price: number;
};

export type BrandPosition = {
  brand: string;
  products: number;
  avg_price: number;
  min_price: number;
  max_price: number;
  price_index: number | null;
  avg_rating: number | null;
  reviews: number;
  in_stock_pct: number | null;
  avg_discount_pct: number | null;
  value_score: number | null;
};

export type PriceGap = {
  lower_price: number;
  upper_price: number;
  gap: number;
  gap_pct: number;
  below: string;
  above: string;
};

export type PriceIntelligence = {
  category: string | null;
  distribution: Partial<{
    count: number;
    currency: string;
    min: number;
    p25: number;
    median: number;
    p75: number;
    p90: number;
    max: number;
    mean: number;
  }>;
  brands: BrandPosition[];
  gaps: PriceGap[];
  observations: string[];
};

export type AspectSummary = {
  aspect: string;
  mentions: number;
  avg_score: number;
  positive: number;
  negative: number;
  brands: Record<string, number>;
  evidence: { review_id: string; brand?: string; quote: string; score: number }[];
};

export type ExecutiveReport = {
  category: string | null;
  generated_at: string;
  products_analysed: number;
  reviews_analysed: number;
  headline: string;
  summary: string;
  competitors: {
    brand: string;
    positioning: string;
    strengths: string[];
    weaknesses: string[];
  }[];
  opportunities: { claim: string; supporting_metric: string | null }[];
  threats: { claim: string; supporting_metric: string | null }[];
  recommendations: { action: string; rationale: string; priority: string }[];
  sentiment: {
    aspects: AspectSummary[];
    reviews_analysed: number;
    mentions_kept: number;
    mentions_discarded: number;
  };
  citations_dropped: number;
  usage: { total_tokens?: number; llm_calls?: number; models?: string[] };
};

export type PriceMove = {
  product_id: string;
  title: string;
  brand: string;
  from_price: number;
  to_price: number;
  change: number;
  change_pct: number;
  direction: "up" | "down";
  from_day: string;
  to_day: string;
  url: string;
};

export type MarketChanges = {
  category: string | null;
  days: number;
  baseline_day: string | null;
  latest_day: string | null;
  days_observed: number;
  has_history: boolean;
  median_before: number | null;
  median_after: number | null;
  median_change_pct: number | null;
  price_moves: PriceMove[];
  stock_flips: { product_id: string; title: string; brand: string; in_stock: boolean }[];
  new_products: { product_id: string; title: string; brand: string; price: number }[];
  disappeared: { product_id: string; title: string; brand: string; price: number }[];
  observations: string[];
};

export type HistoryPoint = {
  day: string;
  products: number;
  median_price: number;
  min_price: number;
  max_price: number;
  p90_price: number;
  in_stock_pct: number;
};

export type History = {
  category: string | null;
  since: string;
  days_observed: number;
  series: HistoryPoint[];
};

export type AskResponse = {
  answer: string;
  citations: string[];
  hits: { review_id?: string; brand?: string; product_title?: string; text: string; score: number }[];
  usage: { total_tokens?: number };
};
