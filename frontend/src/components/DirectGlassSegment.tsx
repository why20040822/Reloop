import { useEffect, useId, useState, type CSSProperties, type Ref } from "react";

type Option = { value: string; label: string };
type Props = {
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
  containerRef?: Ref<HTMLDivElement>;
};

export function DirectGlassSegment({ value, options, onChange, ariaLabel, className = "", containerRef }: Props) {
  const [dragging, setDragging] = useState(false);
  const id = useId();
  const selected = Math.max(0, options.findIndex((option) => option.value === value));

  useEffect(() => {
    const stop = () => setDragging(false);
    window.addEventListener("pointerup", stop);
    return () => window.removeEventListener("pointerup", stop);
  }, []);

  return (
    <div
      className={`direct-glass-segment ${dragging ? "is-dragging" : ""} ${className}`}
      ref={containerRef}
      role="radiogroup"
      aria-label={ariaLabel}
      style={{ "--dg-count": options.length, "--dg-index": selected } as CSSProperties}
    >
      <span className="direct-glass-lens" aria-hidden="true" />
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          role="radio"
          aria-checked={option.value === value}
          data-segment-value={option.value}
          className={option.value === value ? "active" : ""}
          onPointerDown={() => setDragging(true)}
          onClick={() => onChange(option.value)}
          aria-describedby={id}
        >
          {option.label}
        </button>
      ))}
      <span id={id} className="sr-only">{ariaLabel}</span>
    </div>
  );
}
