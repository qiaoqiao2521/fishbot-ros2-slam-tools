import type { LaserScanPointSnapshot, LaserScanSnapshot } from '@/types/station'

export type RadarLayerMode = 'scan' | 'scan+pose' | 'scan+map'

export type RadarWorkbenchConfig = {
  zoom: number
  freeze: boolean
  showGhost: boolean
  showSweep: boolean
  showGrid: boolean
  layerMode: RadarLayerMode
}

export type RadarSelectedPoint = LaserScanPointSnapshot

export type RadarWorkbenchMetrics = {
  beamCount: number
  sampleCount: number
  validRatio: number
  nearFieldCount: number
  coverageRatio: number
  obstructionLevel: 'low' | 'moderate' | 'high'
}

export function createDefaultRadarWorkbenchConfig(): RadarWorkbenchConfig {
  return {
    zoom: 1,
    freeze: false,
    showGhost: true,
    showSweep: true,
    showGrid: true,
    layerMode: 'scan',
  }
}

export function buildRadarWorkbenchMetrics(scan: LaserScanSnapshot): RadarWorkbenchMetrics {
  const beamCount = Math.max(scan.beamCount, 1)
  const sampleCount = scan.samplePoints.length
  const validRatio = (sampleCount / beamCount) * 100

  const sectorHits = new Set<number>()
  const nearFieldCount = scan.samplePoints.filter((point) => {
    const normalized = ((point.angleRad + Math.PI) / (Math.PI * 2)) * 12
    sectorHits.add(Math.max(0, Math.min(11, Math.floor(normalized))))
    return point.rangeMeters <= 0.8
  }).length

  const coverageRatio = (sectorHits.size / 12) * 100
  const obstructionLevel = nearFieldCount >= 8 ? 'high' : nearFieldCount >= 3 ? 'moderate' : 'low'

  return {
    beamCount,
    sampleCount,
    validRatio,
    nearFieldCount,
    coverageRatio,
    obstructionLevel,
  }
}
