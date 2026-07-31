"use client";

/** Shared surfaces: one border style, one label style, one loading style. */

export function Panel({
  title,
  hint,
  loading = false,
  padded = true,
  children,
}: {
  title: string;
  hint?: string;
  loading?: boolean;
  padded?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-4 py-2.5">
        <h2 className="eyebrow text-ink">{title}</h2>
        {hint && <p className="eyebrow normal-case">{hint}</p>}
      </div>
      <div className={padded ? "p-4" : ""}>
        {loading ? <PanelSkeleton /> : children}
      </div>
    </section>
  );
}

export function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden />;
}

/**
 * Bars of decreasing width read as "content is coming" rather than "something
 * broke" — the point of a skeleton over a spinner.
 */
function PanelSkeleton() {
  return (
    <div className="space-y-2.5" role="status" aria-busy="true">
      {[100, 82, 64, 88, 46].map((width, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${width}%` }} />
      ))}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-subtle py-10 text-center text-sm">{children}</p>
  );
}
