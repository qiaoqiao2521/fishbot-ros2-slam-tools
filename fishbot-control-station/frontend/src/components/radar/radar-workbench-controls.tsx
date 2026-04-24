import { Ghost, Grid3X3, Pause, Play, ScanLine, Search, SearchCheck, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { RadarLayerMode, RadarWorkbenchConfig } from '@/lib/radar-workbench'

const layerModes: RadarLayerMode[] = ['scan', 'scan+pose', 'scan+map']

export function RadarWorkbenchControls({
  config,
  onClearHistory,
  onConfigChange,
}: {
  config: RadarWorkbenchConfig
  onConfigChange: (next: RadarWorkbenchConfig) => void
  onClearHistory: () => void
}) {
  return (
    <div className="glass-panel rounded-[28px] px-5 py-4">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant={config.freeze ? 'default' : 'outline'}
            size="sm"
            onClick={() => onConfigChange({ ...config, freeze: !config.freeze })}
          >
            {config.freeze ? <Play className="mr-2 h-4 w-4" /> : <Pause className="mr-2 h-4 w-4" />}
            {config.freeze ? 'Resume' : 'Freeze'}
          </Button>

          <Button
            variant={config.showGhost ? 'default' : 'outline'}
            size="sm"
            onClick={() => onConfigChange({ ...config, showGhost: !config.showGhost })}
          >
            <Ghost className="mr-2 h-4 w-4" />
            Ghost
          </Button>

          <Button
            variant={config.showSweep ? 'default' : 'outline'}
            size="sm"
            onClick={() => onConfigChange({ ...config, showSweep: !config.showSweep })}
          >
            <ScanLine className="mr-2 h-4 w-4" />
            Sweep
          </Button>

          <Button
            variant={config.showGrid ? 'default' : 'outline'}
            size="sm"
            onClick={() => onConfigChange({ ...config, showGrid: !config.showGrid })}
          >
            <Grid3X3 className="mr-2 h-4 w-4" />
            Grid
          </Button>

          <Button variant="outline" size="sm" onClick={onClearHistory}>
            <Trash2 className="mr-2 h-4 w-4" />
            Clear
          </Button>
        </div>

        <div className="flex flex-col gap-3 xl:items-end">
          <div className="flex flex-wrap items-center gap-2">
            {layerModes.map((mode) => (
              <Button
                key={mode}
                variant={config.layerMode === mode ? 'default' : 'outline'}
                size="sm"
                onClick={() => onConfigChange({ ...config, layerMode: mode })}
              >
                {mode === 'scan' ? <Search className="mr-2 h-4 w-4" /> : <SearchCheck className="mr-2 h-4 w-4" />}
                {mode}
              </Button>
            ))}
          </div>

          <div className="flex items-center gap-3 text-xs uppercase tracking-[0.18em] text-muted-foreground">
            <span>zoom</span>
            <input
              className="h-2 w-44 accent-[hsl(var(--accent))]"
              type="range"
              min={0.65}
              max={1.8}
              step={0.05}
              value={config.zoom}
              onChange={(event) => onConfigChange({ ...config, zoom: Number(event.target.value) })}
            />
            <span className="station-readout text-foreground/92">{Math.round(config.zoom * 100)}%</span>
          </div>
        </div>
      </div>
    </div>
  )
}
