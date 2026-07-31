"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Dict } from "@/lib/i18n";
import type { AspectSummary, BrandPosition, HistoryPoint } from "@/lib/types";

// Charts inherit the page's ink colour so they invert with the theme instead of
// carrying their own greys.
const AXIS = {
  fontSize: 10,
  fontFamily: "var(--font-geist-mono)",
  fill: "currentColor",
  opacity: 0.45,
  letterSpacing: "0.06em",
};

const COLOR = {
  accent: "var(--accent)",
  positive: "var(--positive)",
  negative: "var(--negative)",
  warn: "var(--warn)",
  line: "var(--line-strong)",
};

const tooltipStyle = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--line-strong)",
    borderRadius: 0,
    fontSize: 12,
    fontFamily: "var(--font-geist-mono)",
    color: "var(--ink)",
    padding: "8px 10px",
  },
  labelStyle: {
    color: "var(--subtle)",
    fontSize: 10,
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
  },
  cursor: { fill: "var(--inset)" },
} as const;

/** Average price per brand, coloured by position against the category median. */
export function BrandPriceChart({ brands, t }: { brands: BrandPosition[]; t: Dict }) {
  const data = brands
    .slice()
    .sort((a, b) => b.avg_price - a.avg_price)
    .map((b) => ({
      brand: b.brand,
      price: b.avg_price,
      index: b.price_index ?? 100,
    }));

  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 32)}>
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 40 }}>
        <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis
          type="category"
          dataKey="brand"
          width={100}
          tick={AXIS}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          {...tooltipStyle}
          formatter={(value) => [Number(value ?? 0).toFixed(2), t.avgPriceLabel]}
        />
        <Bar dataKey="price" isAnimationActive={false}>
          {data.map((d) => (
            // Above the category median = pressure (warn), below = value.
            <Cell key={d.brand} fill={d.index >= 100 ? COLOR.warn : COLOR.positive} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Median price over time, with the min–p90 band behind it.
 *
 * The band matters: a flat median can hide the cheap end collapsing while the
 * premium end holds, and that is exactly the move worth reacting to.
 */
export function PriceTrendChart({ series, t }: { series: HistoryPoint[]; t: Dict }) {
  const data = series.map((point) => ({
    ...point,
    label: point.day.slice(5), // MM-DD is enough on a 30-day axis
    band: [point.min_price, point.p90_price] as [number, number],
  }));

  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <XAxis
          dataKey="label"
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          minTickGap={28}
        />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} />
        <Tooltip
          {...tooltipStyle}
          cursor={{ stroke: COLOR.line, strokeWidth: 1 }}
          formatter={(value, name) => {
            if (name === "band" && Array.isArray(value)) {
              return [
                `${Number(value[0]).toFixed(0)} – ${Number(value[1]).toFixed(0)}`,
                t.rangeLabel,
              ];
            }
            return [Number(value ?? 0).toFixed(2), t.medianPrice];
          }}
        />
        <Area
          dataKey="band"
          stroke="none"
          fill={COLOR.accent}
          fillOpacity={0.1}
          isAnimationActive={false}
        />
        <Line
          dataKey="median_price"
          stroke={COLOR.accent}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

type Datum = {
  aspect: string;
  score: number;
  mentions: number;
  negative: number;
  positive: number;
};

/** Aspect sentiment as a diverging bar: left of zero is a complaint. */
export function AspectSentimentChart({
  aspects,
  t,
}: {
  aspects: AspectSummary[];
  t: Dict;
}) {
  const data: Datum[] = aspects
    .slice()
    .sort((a, b) => a.avg_score - b.avg_score)
    .map((a) => ({
      aspect: a.aspect,
      score: a.avg_score,
      mentions: a.mentions,
      negative: a.negative,
      positive: a.positive,
    }));

  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 30)}>
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 16 }}>
        <XAxis
          type="number"
          domain={[-1, 1]}
          ticks={[-1, -0.5, 0, 0.5, 1]}
          tick={AXIS}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="aspect"
          width={140}
          tick={AXIS}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          {...tooltipStyle}
          formatter={(value, _name, item) => {
            const score = Number(value ?? 0);
            const row = item?.payload as Datum | undefined;
            return [
              `${score >= 0 ? "+" : ""}${score.toFixed(2)} · ${row?.mentions ?? 0} ${t.mentions} ` +
                `(${row?.positive ?? 0}+ / ${row?.negative ?? 0}−)`,
              t.sentiment,
            ];
          }}
        />
        <ReferenceLine x={0} stroke={COLOR.line} />
        <Bar dataKey="score" isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.aspect} fill={d.score < 0 ? COLOR.negative : COLOR.positive} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
