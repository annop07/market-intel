"""Render an ExecutiveReport as Markdown.

The nightly CI job commits this file to reports/, so the repository doubles as
the report archive: open any dated file and see what the market looked like.

Section headings follow the report's own language — a Thai report whose
scaffolding is in English reads like a half-finished translation.
"""
from __future__ import annotations

from app.analysis.report import ExecutiveReport

LABELS = {
    "en": {
        "title": "Market Intelligence",
        "generated": "Generated {when} · {products} products · {reviews} reviews analysed",
        "price_landscape": "Price landscape",
        "currency_note": "All figures in {currency}, converted at a static rate.",
        "changed": "What changed",
        "changed_hint": "{baseline} → {latest}, {days} day(s) of history",
        "move_columns": ["Product", "Brand", "Before", "After", "Change"],
        "no_history": (
            "Only one crawl so far — trend analysis starts with the second run."
        ),
        "competitor_positions": "Competitor positions",
        "columns": [
            "Brand", "Products", "Avg price", "Price index", "Avg rating",
            "In stock", "Avg discount",
        ],
        "index_note": "Price index: 100 = category median.",
        "brand_profiles": "Brand profiles",
        "strengths": "Strengths",
        "weaknesses": "Weaknesses",
        "aspects": "What customers actually talk about",
        "aspect_columns": [
            "Aspect", "Mentions", "Avg sentiment", "Positive", "Negative", "Loudest brands",
        ],
        "complaints": "Sharpest complaints, in customers' words",
        "opportunities": "Opportunities",
        "threats": "Threats",
        "recommendations": "Recommendations",
        "gaps": "Unoccupied price bands",
        "gap_line": "between *{below}* and *{above}*",
        "method": "How this was produced",
        "method_numbers": (
            "Prices, indices, discounts and stock rates are computed in SQL from the "
            "collected catalogue — the model never calculates a number."
        ),
        "method_sentiment": (
            "Sentiment is aspect-level over {reviews} reviews; {kept} mentions kept, "
            "{discarded} discarded for citing a review that was not in the batch or "
            "quoting text it does not contain."
        ),
        "method_citations": (
            "{dropped} citation(s) in the narrative pointed at unknown reviews and were stripped."
        ),
        "method_cost": "LLM cost: {tokens} tokens over {calls} call(s) — {models}.",
        "evidence": "evidence",
        "all_categories": "all categories",
    },
    "th": {
        "title": "รายงานข่าวกรองตลาด",
        "generated": "สร้างเมื่อ {when} · สินค้า {products} รายการ · วิเคราะห์รีวิว {reviews} ชิ้น",
        "price_landscape": "ภาพรวมราคาในตลาด",
        "currency_note": "ตัวเลขทั้งหมดเป็นสกุล {currency} แปลงค่าด้วยอัตราคงที่",
        "changed": "อะไรเปลี่ยนไปบ้าง",
        "changed_hint": "{baseline} → {latest} · มีประวัติ {days} วัน",
        "move_columns": ["สินค้า", "แบรนด์", "ก่อน", "หลัง", "เปลี่ยนแปลง"],
        "no_history": "เพิ่งเก็บข้อมูลครั้งแรก — การวิเคราะห์แนวโน้มจะเริ่มจากการเก็บครั้งที่สอง",
        "competitor_positions": "ตำแหน่งของคู่แข่ง",
        "columns": [
            "แบรนด์", "จำนวนสินค้า", "ราคาเฉลี่ย", "ดัชนีราคา", "คะแนนเฉลี่ย",
            "มีของ", "ส่วนลดเฉลี่ย",
        ],
        "index_note": "ดัชนีราคา: 100 = ค่ามัธยฐานของหมวดนี้",
        "brand_profiles": "โปรไฟล์รายแบรนด์",
        "strengths": "จุดแข็ง",
        "weaknesses": "จุดอ่อน",
        "aspects": "สิ่งที่ลูกค้าพูดถึงจริง",
        "aspect_columns": [
            "ประเด็น", "จำนวนที่พูดถึง", "คะแนนเฉลี่ย", "เชิงบวก", "เชิงลบ", "แบรนด์ที่ถูกพูดถึงมากสุด",
        ],
        "complaints": "คำบ่นที่หนักที่สุด จากปากลูกค้าเอง",
        "opportunities": "โอกาส",
        "threats": "ความเสี่ยง",
        "recommendations": "ข้อเสนอแนะ",
        "gaps": "ช่วงราคาที่ยังไม่มีใครจับ",
        "gap_line": "ระหว่าง *{below}* กับ *{above}*",
        "method": "รายงานนี้ผลิตขึ้นอย่างไร",
        "method_numbers": (
            "ราคา ดัชนี ส่วนลด และอัตราสินค้าคงคลัง คำนวณด้วย SQL จากข้อมูลที่เก็บมาจริง "
            "— โมเดลไม่ได้คำนวณตัวเลขใดเลย"
        ),
        "method_sentiment": (
            "วิเคราะห์ความรู้สึกระดับประเด็นจากรีวิว {reviews} ชิ้น เก็บไว้ {kept} รายการ "
            "ตัดทิ้ง {discarded} รายการ เพราะอ้าง review ที่ไม่ได้ส่งให้ หรือยกข้อความที่ไม่มีอยู่จริง"
        ),
        "method_citations": "การอ้างอิงในเนื้อรายงาน {dropped} จุด ชี้ไปยังรีวิวที่ไม่มีอยู่ และถูกตัดออก",
        "method_cost": "ต้นทุน LLM: {tokens} tokens จาก {calls} ครั้ง — {models}",
        "evidence": "หลักฐาน",
        "all_categories": "ทุกหมวดหมู่",
    },
}


def report_to_markdown(report: ExecutiveReport) -> str:
    L = LABELS.get(report.language, LABELS["en"])
    scope = report.category or L["all_categories"]

    md: list[str] = [
        f"# {L['title']} — {scope}",
        "",
        "*"
        + L["generated"].format(
            when=f"{report.generated_at:%Y-%m-%d %H:%M UTC}",
            products=report.products_analysed,
            reviews=report.reviews_analysed,
        )
        + "*",
        "",
        f"> **{report.headline}**",
        "",
        report.summary,
        "",
    ]

    dist = report.pricing.distribution
    if dist.get("count"):
        md += [
            f"## {L['price_landscape']}",
            "",
            "| min | p25 | median | p75 | p90 | max |",
            "| --- | --- | --- | --- | --- | --- |",
            f"| {dist['min']} | {dist['p25']} | {dist['median']} | "
            f"{dist['p75']} | {dist['p90']} | {dist['max']} |",
            "",
            f"*{L['currency_note'].format(currency=dist.get('currency', 'USD'))}*",
            "",
        ]

    # What moved leads the report: a competitor cutting price this week outranks
    # a price difference that has been true for months.
    changes = report.changes
    if changes and changes.has_history:
        md += [
            f"## {L['changed']}",
            "",
            "*"
            + L["changed_hint"].format(
                baseline=changes.baseline_day,
                latest=changes.latest_day,
                days=changes.days_observed,
            )
            + "*",
            "",
        ]
        md += [f"- {o}" for o in changes.observations]
        md.append("")

        if changes.price_moves:
            md += [
                "| " + " | ".join(L["move_columns"]) + " |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
            for m in changes.price_moves[:10]:
                arrow = "▼" if m.direction == "down" else "▲"
                md.append(
                    f"| {m.title} | {m.brand} | {m.from_price:.2f} | {m.to_price:.2f} | "
                    f"{arrow} {abs(m.change_pct):.1f}% |"
                )
            md.append("")
    elif changes:
        md += [f"## {L['changed']}", "", f"*{L['no_history']}*", ""]

    if report.pricing.brands:
        md += [
            f"## {L['competitor_positions']}",
            "",
            "| " + " | ".join(L["columns"]) + " |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for b in report.pricing.brands:
            md.append(
                f"| {b.brand} | {b.products} | {b.avg_price:.2f} | "
                f"{_num(b.price_index)} | {_num(b.avg_rating)} | "
                f"{_pct(b.in_stock_pct)} | {_pct(b.avg_discount_pct)} |"
            )
        md += ["", f"*{L['index_note']}*", ""]

    if report.competitors:
        md += [f"## {L['brand_profiles']}", ""]
        for c in report.competitors:
            md += [f"### {c.brand}", "", c.positioning, ""]
            if c.strengths:
                md.append(f"**{L['strengths']}:** " + ", ".join(c.strengths))
            if c.weaknesses:
                md.append(f"**{L['weaknesses']}:** " + ", ".join(c.weaknesses))
            if c.evidence_review_ids:
                md += ["", f"<sub>{_cites(c.evidence_review_ids, L)}</sub>"]
            md.append("")

    if report.sentiment.aspects:
        md += [
            f"## {L['aspects']}",
            "",
            "| " + " | ".join(L["aspect_columns"]) + " |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for a in report.sentiment.aspects:
            brands = ", ".join(f"{b} ({n})" for b, n in list(a.brands.items())[:3])
            md.append(
                f"| {a.aspect} | {a.mentions} | {a.avg_score:+.2f} | "
                f"{a.positive} | {a.negative} | {brands} |"
            )
        md.append("")

        negative = [a for a in report.sentiment.aspects if a.avg_score < 0][:3]
        if negative:
            md += [f"### {L['complaints']}", ""]
            for aspect in negative:
                for e in aspect.evidence[:2]:
                    md.append(
                        f'- **{aspect.aspect}** — "{e["quote"]}" '
                        f'<sub>{e.get("brand")} · {e["review_id"]}</sub>'
                    )
            md.append("")

    for key, findings in (
        ("opportunities", report.opportunities),
        ("threats", report.threats),
    ):
        if findings:
            md += [f"## {L[key]}", ""]
            for f in findings:
                line = f"- {f.claim}"
                if f.supporting_metric:
                    line += f" *({f.supporting_metric})*"
                if f.evidence_review_ids:
                    line += f" <sub>{_cites(f.evidence_review_ids, L)}</sub>"
                md.append(line)
            md.append("")

    if report.recommendations:
        md += [f"## {L['recommendations']}", ""]
        for r in sorted(report.recommendations, key=_priority_rank):
            md.append(f"- **[{r.priority}]** {r.action} — {r.rationale}")
        md.append("")

    if report.pricing.gaps:
        md += [f"## {L['gaps']}", ""]
        for g in report.pricing.gaps:
            md.append(
                f"- {g.lower_price:.2f} → {g.upper_price:.2f} "
                f"(gap {g.gap:.2f}, +{g.gap_pct:.0f}%) "
                + L["gap_line"].format(below=g.below, above=g.above)
            )
        md.append("")

    usage = report.usage or {}
    md += [
        "---",
        "",
        f"### {L['method']}",
        "",
        f"- {L['method_numbers']}",
        "- "
        + L["method_sentiment"].format(
            reviews=report.sentiment.reviews_analysed,
            kept=report.sentiment.mentions_kept,
            discarded=report.sentiment.mentions_discarded,
        ),
        "- " + L["method_citations"].format(dropped=report.citations_dropped),
        "- "
        + L["method_cost"].format(
            tokens=usage.get("total_tokens", 0),
            calls=usage.get("llm_calls", 0),
            models=", ".join(usage.get("models", [])) or "n/a",
        ),
        "",
    ]
    return "\n".join(md)


def _num(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


def _pct(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "—"


def _cites(ids: list[str], labels: dict) -> str:
    return f"{labels['evidence']}: " + ", ".join(f"`{i}`" for i in ids[:4])


def _priority_rank(rec) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(rec.priority, 3)
