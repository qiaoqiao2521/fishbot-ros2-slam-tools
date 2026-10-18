import { useEffect, useMemo, useRef, useState } from 'react'
import { Box, FileUp, Focus, RefreshCw } from 'lucide-react'
import { useWorkspaceVisible } from '@/components/workspace/workspace-visibility'
import { FISHBOT_PREVIEW_URDF, SCENE_ASSET_BYTES, SCENE_MODELS, sceneAssetFormat, sceneMapPath, sceneMapPose,
  type SceneAssetFormat, type ScenePoints, type SceneSource } from '@/lib/scene-contract'
import { SceneFramePipeline, type SceneWorkerPort } from '@/lib/scene-frame-pipeline'
import { disposeSceneObject, parseSceneModel } from '@/lib/scene-loaders'
import { scheduleSceneSetup } from '@/lib/scene-setup'
import type { LaserScanSnapshot, NavigationSnapshot, RobotStateSnapshot } from '@/types/station'
import { SceneRenderer, type SceneRenderData, type SceneViewMode, type SceneStartupTiming } from './scene-renderer'
import './scene-viewport.css'

export type SceneViewportProps = {
  scan: LaserScanSnapshot
  navigation: NavigationSnapshot
  robotState?: RobotStateSnapshot
  source: SceneSource
  active?: boolean
}
type LocalAsset = { id: number; name: string; format: SceneAssetFormat; bytes: ArrayBuffer }
const EMPTY_POINTS = new Float32Array()

/** Read-only projection. Its lifetime never owns a ROS subscription, task or command. */
export function SceneViewport({ scan, navigation, source, active = true }: SceneViewportProps) {
  const panelVisible = useWorkspaceVisible(), visible = active && panelVisible
  const [mode, setMode] = useState<SceneViewMode>('map')
  const [retry, setRetry] = useState(0)
  const [pointFrame, setPointFrame] = useState<{ scope: string; value: ScenePoints } | null>(null)
  const [asset, setAsset] = useState<LocalAsset | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)
  const [dataError, setDataError] = useState<string | null>(null)
  const [assetError, setAssetError] = useState<string | null>(null)
  const [preparing, setPreparing] = useState(true)
  const [chromeReady, setChromeReady] = useState(false)
  const [rendererEpoch, setRendererEpoch] = useState(0)
  const [startup, setStartup] = useState<SceneStartupTiming>({ firstDrawMs: null, firstModelDrawMs: null })
  const host = useRef<HTMLDivElement>(null), renderer = useRef<SceneRenderer | null>(null)
  const pipeline = useRef<SceneFramePipeline | null>(null)
  const fileSequence = useRef(0)
  const scope = mode === 'asset' && asset ? `file:${asset.id}` : source.key ? `${source.key}:${mode}` : null
  const points = pointFrame?.scope === scope ? pointFrame.value : null
  const evaluated = useMemo<{ data: SceneRenderData; error: string | null }>(() => {
    try {
      return { data: { mode, points, path: source.key ? sceneMapPath(navigation) : EMPTY_POINTS,
        pose: source.key ? sceneMapPose(navigation) : null }, error: null }
    } catch (error) { return { data: { mode, points, path: EMPTY_POINTS, pose: null }, error: error instanceof Error ? error.message : '路径数据无效。' } }
  }, [mode, points, navigation, source.key])
  const data = evaluated.data
  const currentData = useRef(data)
  useEffect(() => { currentData.current = data; renderer.current?.update(data) }, [data])

  useEffect(() => {
    if (!visible || !host.current) return
    const target = host.current, requestedAt = performance.now()
    let current: SceneRenderer | null = null, disposed = false
    setPreparing(true); setStartup({ firstDrawMs: null, firstModelDrawMs: null })
    const cancelSetup = scheduleSceneSetup(() => {
      // Expand the full controls only after the visible preparation frame.
      // Do this before constructing WebGL so creation errors keep recovery UI.
      setChromeReady(true)
      try {
        current = new SceneRenderer(target,
          () => setRenderError('三维图形上下文已丢失。原任务继续；可重建此视图。'),
          () => setRetry((value) => value + 1), setStartup, requestedAt)
        renderer.current = current; setRendererEpoch(value => value + 1); setRenderError(null); current.update(currentData.current)
        target.dataset.sceneSetupMs = String(performance.now() - requestedAt)
      } catch { setPreparing(false); setRenderError('浏览器未能创建 WebGL 三维视图。可重建视图，或继续使用二维地图。'); return }
      const created = current
      void parseSceneModel('urdf', new TextEncoder().encode(FISHBOT_PREVIEW_URDF).buffer).then((model) => {
        if (disposed) { disposeSceneObject(model); return }
        created.setModel(model); created.update(currentData.current); created.fit(); setPreparing(false)
        target.dataset.sceneModelReadyMs = String(performance.now() - requestedAt)
      }).catch((error: unknown) => { if (!disposed) { setPreparing(false); setRenderError(error instanceof Error ? error.message : '简化模型加载失败。') } })
    })
    return () => { disposed = true; cancelSetup(); current?.dispose(); if (renderer.current === current) renderer.current = null }
  }, [visible, retry, source.key])

  useEffect(() => {
    if (!visible) return
    const target = host.current
    const current = new SceneFramePipeline(
      () => new Worker(new URL('./scene.worker.ts', import.meta.url), { type: 'module' }) as unknown as SceneWorkerPort,
      (value) => { if (scope) setPointFrame({ scope, value }); setDataError(null) }, setDataError,
      (metrics) => { if (target) for (const [key, value] of Object.entries(metrics)) target.dataset[`sceneWorker${key[0].toUpperCase()}${key.slice(1)}`] = String(value) })
    pipeline.current = current
    current.setScope(mode === 'map' ? null : scope)
    return () => { current.dispose(); if (pipeline.current === current) pipeline.current = null }
  }, [visible, retry, scope, mode])

  useEffect(() => {
    if (visible && mode === 'scan' && source.key && scan.ready) pipeline.current?.offer({ kind: 'scan', scan })
  }, [scan, visible, mode, source.key, retry])

  useEffect(() => {
    if (!visible || !asset || mode !== 'asset') return
    const current = renderer.current
    if (!current) return
    let disposed = false
    if (asset.format === 'pcd') pipeline.current?.offer({ kind: 'pcd', bytes: asset.bytes })
    else void parseSceneModel(asset.format, asset.bytes).then((model) => {
      if (disposed || renderer.current !== current) { disposeSceneObject(model); return }
      // glTF is Y-up by specification; convert to the view's ROS Z-up once.
      if (asset.format !== 'urdf') model.rotation.x = Math.PI / 2
      current.setAsset(model); current.update(currentData.current); current.fit(); setAssetError(null)
    }).catch((error: unknown) => { if (!disposed) setAssetError(error instanceof Error ? error.message : '文件解析失败。') })
    return () => { disposed = true; current.setAsset(null) }
  }, [asset, visible, mode, retry, source.key, rendererEpoch])

  useEffect(() => {
    if (mode === 'asset' && points?.kind === 'pcd_file') renderer.current?.fit()
  }, [mode, points])

  async function openFile(file: File | undefined): Promise<void> {
    if (!file) return
    const id = ++fileSequence.current
    try {
      const format = sceneAssetFormat(file.name)
      if (!file.size || file.size > SCENE_ASSET_BYTES) throw new Error('文件为空或超过 8 MiB 上限。')
      const bytes = await file.arrayBuffer()
      if (id !== fileSequence.current) return
      setAssetError(null); setDataError(null); setAsset({ id, name: file.name, format, bytes }); setMode('asset')
    } catch (error) { if (id === fileSequence.current) setAssetError(error instanceof Error ? error.message : '文件读取失败。') }
  }
  const error = renderError ?? assetError ?? dataError ?? evaluated.error
  const frameLabel = mode === 'map' ? 'map；米；+Z 向上'
    : mode === 'scan' ? `${points?.frameId ?? scan.frameId ?? '未知'}；传感器局部坐标`
      : asset?.format === 'pcd' ? '文件原始坐标；单位未知' : asset?.format === 'urdf' ? 'URDF；米；+Z 向上' : 'glTF；米；已转换为 +Z 向上'
  const showChrome = chromeReady || !visible
  return <section className="scene-viewport" aria-label="三维只读工作面" aria-busy={!chromeReady && visible}>
    {showChrome && <div className="scene-tools">
      <div className="scene-view-switch" role="group" aria-label="三维显示坐标">
        <button type="button" aria-pressed={mode === 'map'} onClick={() => setMode('map')}>地图与模型</button>
        <button type="button" aria-pressed={mode === 'scan'} onClick={() => setMode('scan')}>激光局部</button>
        {asset && <button type="button" aria-pressed={mode === 'asset'} onClick={() => setMode('asset')}>本地文件</button>}
      </div>
      <div className="scene-view-actions">
        <label className="scene-file"><FileUp size={14} aria-hidden="true" />打开文件<input type="file" accept=".urdf,.gltf,.glb,.pcd" onChange={(event) => { void openFile(event.target.files?.[0]); event.target.value = '' }} /></label>
        <button type="button" onClick={() => renderer.current?.fit()}><Focus size={14} aria-hidden="true" />适应视图</button>
        <button type="button" onClick={() => setRetry((value) => value + 1)}><RefreshCw size={14} aria-hidden="true" />重建视图</button>
      </div>
    </div>}
    {visible ? <div className="scene-stage"><div key={source.key ?? 'unknown'} ref={host} className="scene-webgl" data-scene-mode={mode} />
      {preparing && <p className="scene-preparing" role="status">正在准备三维场景…</p>}</div> : <div className="scene-paused" role="status">三维渲染已暂停；状态读取与原任务继续。</div>}
    {error && <p className="scene-error" role="alert">{error}</p>}
    {!showChrome && <p className="scene-scope">{source.label} · 三维只读；正在准备场景与工具…</p>}
    {showChrome && <><div className="scene-readout" aria-live="polite">
      <span><i className={mode !== 'asset' && source.live ? 'scene-live' : 'scene-history'} />{mode === 'asset' ? `本地文件：${asset?.name ?? ''}（未上传）` : `${source.label} · ${source.live ? '当前读回' : '历史或未核实'}`}</span>
      <span>{frameLabel}</span>
      {points && mode !== 'map' && <span>{points.pointCount} / {points.offeredCount} 点</span>}
      {mode === 'scan' && points?.receivedAt && <span>接收于 {points.receivedAt}；源时间未知</span>}
    </div>
    <div className="scene-startup"><span>场景首帧 {startup.firstDrawMs === null ? '准备中' : `${startup.firstDrawMs.toFixed(1)} ms`}</span>
      <span>模型首帧 {startup.firstModelDrawMs === null ? '未绘制' : `${startup.firstModelDrawMs.toFixed(1)} ms`}</span><small>从本次视图准备到实际绘制；包含初始化等待。</small></div>
    <p className="scene-scope"><Box size={14} aria-hidden="true" />{mode === 'map'
      ? 'FishBot 为简化预览，不是碰撞外廓。模型仅用定位，路径仅用 map 帧；无定位时不拿里程计代替。'
      : mode === 'scan' ? '实际二维 LaserScan 摘要；未取得完整 TF，不与地图强行对齐。接收时间不代表传感器源时间。'
        : '只在本机解析；外部网格和网络资源会被拒绝。文件预览不代表 ROS 场景或任务成功。'}</p>
    <details className="scene-registry"><summary>模型来源与能力</summary>{SCENE_MODELS.map((model) => <div key={model.id}><strong>{model.label}</strong><span>{model.license} · {model.available ? '可预览' : '未打包'} · {model.rootFrame}</span><small>{model.source}</small></div>)}</details></>}
  </section>
}
