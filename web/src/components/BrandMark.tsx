export function Dots({ loading = false, large = false }: { loading?: boolean; large?: boolean }) {
  return (
    <span className={`dots${loading ? " is-loading" : ""}${large ? " lg" : ""}`} aria-hidden="true">
      <i /><i /><i />
    </span>
  );
}

export function BrandMark() {
  return (
    <span className="brand" aria-label="ellipsis">
      ellipsis <Dots />
    </span>
  );
}

/** Brand loading state (§22, §31): the three dots, no spinner. */
export function BrandLoader({ text, fullscreen = false }: { text: string; fullscreen?: boolean }) {
  return (
    <div className={fullscreen ? "fullscreen-loader" : "loader"} role="status" aria-live="polite">
      <span className="brand" style={{ fontSize: 20 }}>ellipsis <Dots loading large /></span>
      <p>{text}</p>
    </div>
  );
}
