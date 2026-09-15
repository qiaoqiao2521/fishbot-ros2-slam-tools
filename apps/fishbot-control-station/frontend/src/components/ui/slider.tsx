type SliderProps = {
  label: string
  value: number
  min: number
  max: number
  step?: number
  suffix?: string
  onChange: (value: number) => void
}

export function Slider({
  label,
  max,
  min,
  onChange,
  step = 0.01,
  suffix = '',
  value,
}: SliderProps) {
  return (
    <label className="block space-y-3">
      <div className="flex items-center justify-between">
        <span className="station-kicker">{label}</span>
        <span className="station-readout text-sm font-semibold text-foreground">
          {value.toFixed(2)}
          {suffix}
        </span>
      </div>
      <input
        className="h-2.5 w-full cursor-pointer appearance-none rounded-full border border-border/60 bg-[rgba(111,86,51,0.12)] accent-[hsl(var(--accent))]"
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="range"
        value={value}
      />
    </label>
  )
}
