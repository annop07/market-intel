"use client";

import { useSyncExternalStore } from "react";

export type Lang = "en" | "th";

export const LANGUAGES: { code: Lang; label: string }[] = [
  { code: "en", label: "EN" },
  { code: "th", label: "ไทย" },
];

const DICT = {
  en: {
    title: "Market Intelligence",
    connecting: "connecting…",
    stats: (p: number, r: number, v: number, s: number) =>
      `${p} products · ${r} reviews · ${v} vectors · ${s} sources`,
    category: "Category",
    apiDown: (base: string) => `— is the API running on ${base}?`,

    latestReport: "Latest report",
    allCategories: "all categories",
    tokens: "tokens",
    reportMeta: (kept: number, discarded: number, dropped: number) =>
      `${kept} verified mentions · ${discarded} discarded · ${dropped} bad citations stripped`,
    noReportForLang:
      "No report has been generated in this language yet — run the pipeline with --language th.",

    products: "Products",
    brands: "Brands",
    medianPrice: "Median price",
    priceSpread: "Price spread",

    brandPrices: "Brand price positions",
    brandPricesHint: "index 100 = category median · above it costs more",
    aspectsTitle: "What customers talk about",
    aspectsHint: "aspect sentiment, from verified review quotes",
    aspectsOtherCategory: (category: string) => `the last report covered “${category}”`,
    emptyNoProducts: "no products in this category",
    emptyRunReport: (category: string) =>
      `run --report --category ${category} to fill this in`,

    findings: "Computed findings",
    findingsHint: "derived in SQL — no model involved",

    trend: "Price trend",
    trendHint: (days: number) => `median price, ${days} day(s) of history`,
    rangeLabel: "min – p90",
    changes: "What changed",
    changesHint: (baseline: string, latest: string) => `${baseline} → ${latest}`,
    noHistory: "Only one crawl so far — trends start with the second run.",
    movers: "Biggest moves",
    cheaper: "cheaper",
    pricier: "pricier",
    wentOut: "went out of stock",
    cameBack: "back in stock",
    newListings: "new listings",
    gone: "disappeared",

    competitors: "Competitor positions",
    colBrand: "Brand",
    colProducts: "Products",
    colAvgPrice: "Avg price",
    colIndex: "Index",
    colRating: "Rating",
    colInStock: "In stock",
    colDiscount: "Discount",

    gaps: "Unoccupied price bands",
    gapsHint: "the widest gaps between neighbouring products",
    gapBetween: (below: string, above: string) => `between ${below} and ${above}`,

    recommendations: "Recommendations",
    recommendationsHint: "from the latest report",

    askTitle: "Ask the review corpus",
    askHint:
      "Semantic search over every collected review, answered only from what customers actually wrote.",
    askPlaceholder: (category?: string) =>
      category ? `Ask about ${category}…` : "Ask about the market…",
    askButton: "Ask",
    asking: "Thinking…",
    evidence: "evidence",
    retrieved: (n: number) => `${n} reviews retrieved`,
    suggestions: [
      "What do customers complain about most?",
      "Which brand has the happiest customers, and why?",
      "What would make someone switch brands?",
    ],

    footer: (model: string) =>
      `Numbers computed in SQL from the collected catalogue · narrative and sentiment by ${model} · every claim cites a review id`,

    sentiment: "sentiment",
    mentions: "mentions",
    avgPriceLabel: "avg price",
  },

  th: {
    title: "ข่าวกรองตลาด",
    connecting: "กำลังเชื่อมต่อ…",
    stats: (p: number, r: number, v: number, s: number) =>
      `สินค้า ${p} รายการ · รีวิว ${r} ชิ้น · เวกเตอร์ ${v} · ${s} แหล่งข้อมูล`,
    category: "หมวดหมู่",
    apiDown: (base: string) => `— API ที่ ${base} รันอยู่หรือเปล่า?`,

    latestReport: "รายงานล่าสุด",
    allCategories: "ทุกหมวดหมู่",
    tokens: "tokens",
    reportMeta: (kept: number, discarded: number, dropped: number) =>
      `ยืนยันได้ ${kept} รายการ · ตัดทิ้ง ${discarded} · การอ้างอิงที่ไม่ถูกต้องถูกลบ ${dropped}`,
    noReportForLang:
      "ยังไม่มีรายงานภาษานี้ — สั่ง pipeline ด้วย --language th เพื่อสร้าง",

    products: "สินค้า",
    brands: "แบรนด์",
    medianPrice: "ราคามัธยฐาน",
    priceSpread: "ช่วงราคา",

    brandPrices: "ตำแหน่งราคาของแต่ละแบรนด์",
    brandPricesHint: "ดัชนี 100 = มัธยฐานของหมวด · เกินกว่านั้นคือแพงกว่า",
    aspectsTitle: "ประเด็นที่ลูกค้าพูดถึง",
    aspectsHint: "คะแนนความรู้สึกรายประเด็น จากข้อความรีวิวที่ตรวจสอบแล้ว",
    aspectsOtherCategory: (category: string) => `รายงานล่าสุดทำไว้ของหมวด “${category}”`,
    emptyNoProducts: "ไม่มีสินค้าในหมวดนี้",
    emptyRunReport: (category: string) =>
      `สั่ง --report --category ${category} เพื่อให้มีข้อมูลตรงนี้`,

    findings: "ข้อค้นพบจากการคำนวณ",
    findingsHint: "คำนวณด้วย SQL — ไม่มีโมเดลเข้ามาเกี่ยวข้อง",

    trend: "แนวโน้มราคา",
    trendHint: (days: number) => `ราคามัธยฐาน · มีประวัติ ${days} วัน`,
    rangeLabel: "ต่ำสุด – p90",
    changes: "อะไรเปลี่ยนไปบ้าง",
    changesHint: (baseline: string, latest: string) => `${baseline} → ${latest}`,
    noHistory: "เพิ่งเก็บข้อมูลครั้งแรก — แนวโน้มจะเริ่มมีตั้งแต่การเก็บครั้งที่สอง",
    movers: "ขยับแรงที่สุด",
    cheaper: "ถูกลง",
    pricier: "แพงขึ้น",
    wentOut: "ของหมด",
    cameBack: "กลับมามีของ",
    newListings: "สินค้าใหม่",
    gone: "หายไป",

    competitors: "ตำแหน่งของคู่แข่ง",
    colBrand: "แบรนด์",
    colProducts: "สินค้า",
    colAvgPrice: "ราคาเฉลี่ย",
    colIndex: "ดัชนี",
    colRating: "คะแนน",
    colInStock: "มีของ",
    colDiscount: "ส่วนลด",

    gaps: "ช่วงราคาที่ยังไม่มีใครจับ",
    gapsHint: "ช่องว่างที่กว้างที่สุดระหว่างสินค้าที่ราคาติดกัน",
    gapBetween: (below: string, above: string) => `ระหว่าง ${below} กับ ${above}`,

    recommendations: "ข้อเสนอแนะ",
    recommendationsHint: "จากรายงานล่าสุด",

    askTitle: "ถามคลังรีวิว",
    askHint: "ค้นเชิงความหมายจากรีวิวทั้งหมดที่เก็บมา ตอบจากสิ่งที่ลูกค้าเขียนจริงเท่านั้น",
    askPlaceholder: (category?: string) =>
      category ? `ถามเกี่ยวกับ ${category}…` : "ถามเกี่ยวกับตลาดนี้…",
    askButton: "ถาม",
    asking: "กำลังคิด…",
    evidence: "หลักฐาน",
    retrieved: (n: number) => `ดึงรีวิวมา ${n} ชิ้น`,
    suggestions: [
      "ลูกค้าบ่นเรื่องอะไรมากที่สุด?",
      "แบรนด์ไหนลูกค้าพอใจที่สุด เพราะอะไร?",
      "อะไรที่จะทำให้ลูกค้าเปลี่ยนไปใช้แบรนด์อื่น?",
    ],

    footer: (model: string) =>
      `ตัวเลขทั้งหมดคำนวณด้วย SQL จากข้อมูลที่เก็บมาจริง · เนื้อความและ sentiment โดย ${model} · ทุกข้อความอ้างอิง review id`,

    sentiment: "ความรู้สึก",
    mentions: "ครั้งที่พูดถึง",
    avgPriceLabel: "ราคาเฉลี่ย",
  },
} as const;

export type Dict = (typeof DICT)["en"];

export function dict(lang: Lang): Dict {
  return DICT[lang] as Dict;
}

const STORAGE_KEY = "market-intel-lang";

// The chosen language lives in localStorage, which is state React does not own.
// useSyncExternalStore is the supported way to read it: the server snapshot is
// "en", so prerendered markup and hydration agree, and React re-renders once
// with the stored value instead of us mutating state inside an effect.
let current: Lang | null = null;
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  // Another tab changing the language keeps this one in sync.
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function getSnapshot(): Lang {
  if (current === null) {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    current = stored === "th" || stored === "en" ? stored : "en";
  }
  return current;
}

function getServerSnapshot(): Lang {
  return "en";
}

function setLanguage(next: Lang): void {
  current = next;
  window.localStorage.setItem(STORAGE_KEY, next);
  document.documentElement.lang = next;
  listeners.forEach((notify) => notify());
}

/** Language state, persisted so a reload keeps the reader's choice. */
export function useLang(): [Lang, (next: Lang) => void] {
  const lang = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return [lang, setLanguage];
}
