export type CooperationSceneProfile = {
  schema: 1
  vehicle: 'fishbot' | 'jackal_j100'
  sensors: 'planar' | 'lidar3d'
  task: 'transport' | 'three_batch_transport'
}

export const DEFAULT_COOPERATION_SCENE_PROFILE: CooperationSceneProfile = {
  schema: 1, vehicle: 'fishbot', sensors: 'planar', task: 'transport',
}
export const SCENE_VEHICLE_LABELS = { fishbot: 'FishBot', jackal_j100: 'Jackal J100' }
export const SCENE_SENSOR_LABELS = { planar: '2D 平面雷达', lidar3d: '2D + 16线 3D 雷达' }
export const SCENE_TASK_LABELS = { transport: '单次装货运输', three_batch_transport: '三批运输（A / A / B）' }
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)

export function parseCooperationSceneProfile(value: unknown): CooperationSceneProfile | null {
  if (!record(value) || Object.keys(value).length !== 4 || value.schema !== 1
    || typeof value.vehicle !== 'string' || !['fishbot', 'jackal_j100'].includes(value.vehicle)
    || typeof value.sensors !== 'string' || !['planar', 'lidar3d'].includes(value.sensors)
    || typeof value.task !== 'string' || !['transport', 'three_batch_transport'].includes(value.task)) return null
  return { schema: 1, vehicle: value.vehicle as CooperationSceneProfile['vehicle'],
    sensors: value.sensors as CooperationSceneProfile['sensors'], task: value.task as CooperationSceneProfile['task'] }
}

export function cooperationSceneProfileDocument(value: CooperationSceneProfile): string {
  const profile = parseCooperationSceneProfile(value)
  if (!profile) throw new Error('场景配置需要有效的车型、传感器和任务。')
  return JSON.stringify(profile, null, 2) + '\n'
}

export function cooperationSceneProfileHref(value: CooperationSceneProfile): string {
  return 'data:application/json;charset=utf-8,' + encodeURIComponent(cooperationSceneProfileDocument(value))
}

export const COOPERATION_PREPARE_COMMAND = `./fishbot.sh cooperation prepare \\
  --so101-project ../so101 \\
  --scene-profile /path/to/cooperation-profile.json \\
  --output "$HOME/.cache/fishbot/cooperation/NEW_SCENE"`

export type CooperationProfileState = { scene_profile?: unknown; vehicle_profile?: unknown }
export function cooperationLiveProfile(state: CooperationProfileState | null | undefined) {
  const profile = parseCooperationSceneProfile(state?.scene_profile)
  const vehicle = record(state?.vehicle_profile) ? state.vehicle_profile : null
  const vehicleId = vehicle && (vehicle.id === 'fishbot' || vehicle.id === 'jackal_j100') ? vehicle.id : null
  const vehicleName = vehicleId ? (typeof vehicle?.label === 'string' && vehicle.label.trim()
    ? vehicle.label : SCENE_VEHICLE_LABELS[vehicleId]) : profile ? SCENE_VEHICLE_LABELS[profile.vehicle] : 'FishBot'
  const missing = state?.scene_profile === undefined || state.scene_profile === null
  const conflict = !!profile && !!vehicleId && profile.vehicle !== vehicleId
  const invalidVehicle = !!vehicle && vehicle.id !== undefined && !vehicleId
  return {
    vehicleName: invalidVehicle ? '未识别车型' : vehicleName,
    sensorsLabel: profile ? SCENE_SENSOR_LABELS[profile.sensors] : '未上报',
    taskLabel: profile ? SCENE_TASK_LABELS[profile.task] : '未上报',
    workflowOwned: profile?.task === 'three_batch_transport',
    note: !state ? '等待协同服务上报实际组合。' : conflict ? '服务上报的场景车型与实际车型不一致，请核对当前 manifest。'
      : invalidVehicle ? '服务上报了未识别车型，未使用配置草稿代替。'
        : missing ? vehicleId ? '旧接口未上报完整场景组合，车型来自服务实际车辆字段。'
          : '旧接口未上报场景组合；FishBot 标签沿用旧版显示，不代表已应用配置草稿。'
          : !profile ? '服务场景组合格式未识别，未使用配置草稿代替。' : '来自当前服务 manifest，与下方配置草稿分别显示。',
    reported: !!state,
  }
}
