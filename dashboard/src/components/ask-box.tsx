"use client";

import { useState } from "react";

import { Skeleton } from "@/components/panel";
import { ask } from "@/lib/api";
import type { Dict, Lang } from "@/lib/i18n";
import type { AskResponse } from "@/lib/types";

export function AskBox({
  category,
  lang,
  t,
}: {
  category?: string;
  lang: Lang;
  t: Dict;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(q: string) {
    if (!q.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      setAnswer(await ask(q, category, lang));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setAnswer(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel">
      <div className="border-b border-line px-4 py-2.5">
        <h2 className="eyebrow text-ink">{t.askTitle}</h2>
        <p className="eyebrow mt-1 normal-case">{t.askHint}</p>
      </div>

      <div className="p-4">
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t.askPlaceholder(category)}
            className="min-w-0 flex-1 border border-line bg-transparent px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <button type="submit" disabled={loading || !question.trim()} className="btn-accent">
            {loading ? t.asking : t.askButton}
            <span aria-hidden>→</span>
          </button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2">
          {t.suggestions.map((s) => (
            <button
              key={s}
              onClick={() => {
                setQuestion(s);
                submit(s);
              }}
              className="btn-ghost"
            >
              {s}
            </button>
          ))}
        </div>

        {error && (
          <p role="alert" className="mt-4 border border-negative/40 px-3 py-2 text-sm text-negative">
            {error}
          </p>
        )}

        {loading && (
          <div className="mt-5 space-y-2" role="status" aria-busy="true">
            <Skeleton className="h-4" />
            <Skeleton className="h-4" style={{ width: "88%" }} />
            <Skeleton className="h-4" style={{ width: "62%" }} />
          </div>
        )}

        {answer && !loading && (
          <div className="mt-5 space-y-3">
            <p className="border-l-2 border-accent pl-4 text-sm leading-relaxed">
              {answer.answer}
            </p>

            {answer.citations.length > 0 && (
              <p className="eyebrow flex flex-wrap items-center gap-x-2 gap-y-1 normal-case">
                <span>{t.evidence}:</span>
                {answer.citations.map((c) => (
                  <code key={c} className="border border-line px-1.5 py-0.5 text-[10px]">
                    {c}
                  </code>
                ))}
              </p>
            )}

            <details className="text-xs">
              <summary className="eyebrow cursor-pointer normal-case hover:text-ink">
                {t.retrieved(answer.hits.length)}
                {answer.usage?.total_tokens
                  ? ` · ${answer.usage.total_tokens} ${t.tokens}`
                  : ""}
              </summary>
              <ul className="mt-3 space-y-2">
                {answer.hits.map((h, i) => (
                  <li key={h.review_id ?? i} className="border-l border-line pl-3">
                    <span className="eyebrow normal-case">
                      {h.brand} · {h.product_title} · {h.score.toFixed(3)}
                    </span>
                    <p className="text-muted mt-0.5">{h.text}</p>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </div>
    </section>
  );
}
