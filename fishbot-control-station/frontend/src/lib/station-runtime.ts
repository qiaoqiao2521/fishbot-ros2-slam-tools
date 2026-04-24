import type {
  ConnectionSnapshot,
  ControlFeedbackSnapshot,
  DiagnosticSnapshot,
  NavigationSnapshot,
  PerceptionSnapshot,
  RobotStateSnapshot,
} from '@/types/station'

type Tone = 'neutral' | 'success' | 'warning' | 'danger'

export type RuntimeModePresentation = {
  label: string
  summary: string
  detail: string
  tone: Tone
  capability: string
}

export type NavigationSlot = {
  title: string
  description: string
  status: string
  tone: Tone
}

export type MapDataSection = {
  title: string
  summary: string
  detail: string
  status: string
  tone: Tone
  hooks: string[]
}

export type MapShellPresentation = {
  label: string
  caption: string
  headingLabel: string
  robotPercentX: number
  robotPercentY: number
  tone: Tone
}

export type ExportSnapshot = {
  exportedAt: string
  mode: ConnectionSnapshot['mode']
  usingFallbackData: boolean
  connection: ConnectionSnapshot
  robotState: RobotStateSnapshot
  navigation: NavigationSnapshot
  perception: PerceptionSnapshot
  diagnostics: DiagnosticSnapshot
  controlFeedback: ControlFeedbackSnapshot
}

export function buildExportSnapshot(
  connection: ConnectionSnapshot,
  robotState: RobotStateSnapshot,
  navigation: NavigationSnapshot,
  perception: PerceptionSnapshot,
  diagnostics: DiagnosticSnapshot,
  controlFeedback: ControlFeedbackSnapshot,
  usingFallbackData: boolean,
): ExportSnapshot {
  return {
    exportedAt: new Date().toISOString(),
    mode: connection.mode,
    usingFallbackData,
    connection,
    robotState,
    navigation,
    perception,
    diagnostics,
    controlFeedback,
  }
}

export function getModePresentation(
  connection: ConnectionSnapshot,
  usingFallbackData: boolean,
): RuntimeModePresentation {
  if (usingFallbackData || connection.mode === 'fallback') {
    return {
      label: 'fallback snapshot',
      summary: '当前界面仍在使用前端兜底快照。',
      detail: '说明后端状态接口或事件流还没有接管，适合调布局，不适合判断真实链路。',
      tone: 'warning',
      capability: 'UI shell only',
    }
  }

  if (connection.mode === 'offline') {
    return {
      label: 'offline simulator',
      summary: '当前是无车开发模式。',
      detail: '控制命令会驱动后端的模拟里程计与 IMU 状态，适合开发控制台、日志和导航占位。',
      tone: 'neutral',
      capability: 'Control + simulated telemetry',
    }
  }

  return {
    label: 'live robot link',
    summary: '当前是实机链路。',
    detail: '状态来自 rosbridge 和 ROS 话题，适合联调真实 `/odom`、`/imu`、`/cmd_vel` 与后续导航状态。',
    tone: connection.robotOnline ? 'success' : 'warning',
    capability: connection.robotOnline ? 'Real telemetry + control' : 'Control path only',
  }
}

export function getNavigationSlots(
  connection: ConnectionSnapshot,
  navigation: NavigationSnapshot,
  usingFallbackData: boolean,
): NavigationSlot[] {
  if (usingFallbackData || connection.mode === 'fallback') {
    return [
      {
        title: 'Map Surface',
        description: '等待后端与事件流接管，再挂地图画布和坐标叠加。',
        status: 'waiting backend stream',
        tone: 'warning',
      },
      {
        title: 'Nav Goal Dispatch',
        description: '先不要下发导航目标，当前只是前端兜底壳层。',
        status: 'ui shell only',
        tone: 'warning',
      },
      {
        title: 'Task / Patrol',
        description: '任务与巡逻流转应在真实后端状态稳定后再接。',
        status: 'blocked by runtime',
        tone: 'warning',
      },
      {
        title: 'Parameter Config',
        description: '参数面板可以先做结构，但不应声称已经接到真实运行态。',
        status: 'structure only',
        tone: 'neutral',
      },
    ]
  }

  if (connection.mode === 'offline') {
    return [
      {
        title: 'Map Surface',
        description: '可以继续做地图容器、工具条和状态叠加，但底层输入仍是模拟位姿。',
        status: 'simulated input',
        tone: 'neutral',
      },
      {
        title: 'Nav Goal Dispatch',
        description: 'UI 和命令流可以先接好，等 Nav2 真状态后再补目标回执和取消语义。',
        status: 'waiting live nav2',
        tone: 'neutral',
      },
      {
        title: 'Task / Patrol',
        description: '可以先定义任务卡片和流程状态，后续直接替换成真实执行结果。',
        status: 'safe to scaffold',
        tone: 'neutral',
      },
      {
        title: 'Parameter Config',
        description: '适合先做运行模式、限速和可视化调参结构。',
        status: 'ready for phase 2',
        tone: 'success',
      },
    ]
  }

  const navReady = navigation.map.ready
    && navigation.tf.mapToOdomPresent
    && navigation.tf.odomToBasePresent
    && navigation.localization.ready
  const navSummary = navigation.navStatus.ready
    ? `${navigation.navStatus.activeGoals} active / ${navigation.navStatus.totalGoals} tracked`
    : 'ready for nav goals'

  return [
    {
      title: 'Map Surface',
      description: '真实地图、TF 和定位状态已经有后端契约，优先把这些状态投到画布和角标。',
      status: navReady ? 'map/tf/localization ready' : 'partial nav graph',
      tone: navReady ? 'success' : 'warning',
    },
    {
      title: 'Nav Goal Dispatch',
      description: '用真实 action status 摘要替掉静态文案，后续再接 goal 下发和取消。',
      status: navSummary,
      tone: navigation.navStatus.ready ? 'success' : 'warning',
    },
    {
      title: 'Task / Patrol',
      description: '任务卡可以直接承接当前 goal 状态计数和 summary，再补 patrol 编排。',
      status: navigation.navStatus.statusSummary || 'ready for missions',
      tone: navigation.navStatus.ready ? 'success' : 'warning',
    },
    {
      title: 'Parameter Config',
      description: '可以开始连真实限速、恢复行为和调试开关。',
      status: 'ready for live tuning',
      tone: 'success',
    },
  ]
}

export function getMapDataSections(
  connection: ConnectionSnapshot,
  navigation: NavigationSnapshot,
  usingFallbackData: boolean,
): MapDataSection[] {
  const mapSource = connection.mode === 'offline'
    ? 'offline odom + imu'
    : connection.mode === 'live'
      ? connection.robotOnline
        ? 'live rosbridge transport'
        : 'live transport, robot quiet'
      : 'fallback UI snapshot'

  if (usingFallbackData || connection.mode === 'fallback') {
    return [
      {
        title: 'Map Source',
        summary: '地图容器先保留，不声称已经拿到真实 `/map`。',
        detail: '这里以后会挂地图栅格、缩放和平移，但当前仍是前端兜底布局。',
        status: 'waiting backend stream',
        tone: 'warning',
        hooks: ['/map', '/map_metadata'],
      },
      {
        title: 'TF Readiness',
        summary: '坐标系树只保留壳层，不把静态或动态 TF 当成已接通。',
        detail: '后续接入时，这一格会直接切到 `/tf` 和 `/tf_static` 的状态摘要。',
        status: 'not wired',
        tone: 'warning',
        hooks: ['/tf', '/tf_static'],
      },
      {
        title: 'Localization Readiness',
        summary: '定位结果暂时只来自兜底快照，不会伪装成 AMCL 或 SLAM 输出。',
        detail: '后续可替换成 `/amcl_pose`、`/odom` 对齐质量和定位置信度。',
        status: 'placeholder pose only',
        tone: 'warning',
        hooks: ['/amcl_pose', '/odom'],
      },
      {
        title: 'Path / Costmap',
        summary: '路径、footprint 和 costmap 只占位，不做实时导航暗示。',
        detail: '这一区域后续直接承接 `/plan`、local/global costmap 和 recovery 状态。',
        status: 'layout reserved',
        tone: 'neutral',
        hooks: ['/plan', '/global_costmap/costmap', '/local_costmap/costmap'],
      },
    ]
  }

  if (connection.mode === 'offline') {
    return [
      {
        title: 'Map Source',
        summary: '地图容器已就位，当前承接的是离线运动学回放。',
        detail: '适合先做 map viewport、缩放控制和机器人 marker，不把它当真机地图流。',
        status: 'simulated pose stream',
        tone: 'neutral',
        hooks: ['/odom', '/imu'],
      },
      {
        title: 'TF Readiness',
        summary: '帧树壳层可以先搭好，但动态 TF 仍是开发占位。',
        detail: '等真机接通后，这一格可以直接换成 `map -> odom -> base_link` 的读数。',
        status: 'static scaffold only',
        tone: 'neutral',
        hooks: ['/tf', '/tf_static'],
      },
      {
        title: 'Localization Readiness',
        summary: '当前位置来自模拟里程计，不冒充 AMCL 定位结果。',
        detail: '这能让你先验证布局、标记和提示词，而不误判 AMCL 或 SLAM 定位链路已经上线。',
        status: 'pose-only dev mode',
        tone: 'neutral',
        hooks: ['/odom', '/amcl_pose'],
      },
      {
        title: 'Path / Costmap',
        summary: '路径和 costmap 的框架可以先摆好，数据仍是静态说明。',
        detail: '后面真接 Nav2 时，这里再接 `/plan`、footprint 和 costmap 热区。',
        status: 'ready for overlay scaffolds',
        tone: 'success',
        hooks: ['/plan', '/global_costmap/costmap', '/local_costmap/costmap'],
      },
    ]
  }

  return [
    {
      title: 'Map Source',
      summary: '真实 `/map` 契约已接到后端，这里直接显示当前栅格摘要。',
      detail: navigation.map.statusMessage,
      status: navigation.map.ready
        ? `${navigation.map.width}x${navigation.map.height} @ ${navigation.map.resolution.toFixed(2)}m / stride ${navigation.map.sampleStride} / ${navigation.map.sampledCells.length} cells`
        : mapSource,
      tone: navigation.map.ready ? 'success' : connection.robotOnline ? 'warning' : 'warning',
      hooks: ['/map', '/map_metadata'],
    },
    {
      title: 'TF Readiness',
      summary: 'TF 图摘要已经存在，直接显示关键帧是否齐全和变换数量。',
      detail: navigation.tf.statusMessage,
      status: navigation.tf.ready
        ? `${navigation.tf.transformCount} transforms / map-odom:${navigation.tf.mapToOdomPresent ? 'yes' : 'no'} / odom-base:${navigation.tf.odomToBasePresent ? 'yes' : 'no'}`
        : connection.robotOnline ? 'transport up, robot quiet' : 'transport up, robot quiet',
      tone: navigation.tf.ready && navigation.tf.mapToOdomPresent && navigation.tf.odomToBasePresent ? 'success' : 'warning',
      hooks: ['/tf', '/tf_static'],
    },
    {
      title: 'Localization Readiness',
      summary: '真实 `/amcl_pose` 摘要已接入，直接显示位姿与置信度。',
      detail: navigation.localization.statusMessage,
      status: navigation.localization.ready
        ? `cov ${navigation.localization.covarianceScore.toFixed(2)} / x ${navigation.localization.x.toFixed(2)} / y ${navigation.localization.y.toFixed(2)}`
        : 'ready for amcl pose',
      tone: navigation.localization.ready ? 'success' : 'warning',
      hooks: ['/amcl_pose', '/odom'],
    },
    {
      title: 'Path / Costmap',
      summary: '先用真实 Nav2 action status 填这一区域，后面再叠路径和 costmap。',
      detail: navigation.navStatus.statusMessage,
      status: navigation.navStatus.ready ? navigation.navStatus.statusSummary : 'ready for nav2 overlays',
      tone: navigation.navStatus.ready ? 'success' : 'warning',
      hooks: ['/plan', '/global_costmap/costmap', '/local_costmap/costmap'],
    },
  ]
}

export function getMapShellPresentation(
  connection: ConnectionSnapshot,
  robotState: RobotStateSnapshot,
  navigation: NavigationSnapshot,
  usingFallbackData: boolean,
): MapShellPresentation {
  const poseX = connection.mode === 'live' && navigation.localization.ready
    ? navigation.localization.x
    : robotState.odom.x
  const poseY = connection.mode === 'live' && navigation.localization.ready
    ? navigation.localization.y
    : robotState.odom.y
  const poseYaw = connection.mode === 'live' && navigation.localization.ready
    ? navigation.localization.yaw
    : robotState.odom.yaw
  const projected = navigation.map.ready
    ? projectPoseToMapPercent(
        poseX,
        poseY,
        navigation.map.originX,
        navigation.map.originY,
        navigation.map.width,
        navigation.map.height,
        navigation.map.resolution,
      )
    : null
  const x = projected ? clamp(projected.x, 2, 98) : clamp(50 + poseX * 18, 8, 92)
  const y = projected ? clamp(projected.y, 2, 98) : clamp(50 - poseY * 18, 8, 92)
  const headingDeg = `${Math.round((poseYaw * 180) / Math.PI)} deg`

  if (usingFallbackData || connection.mode === 'fallback') {
    return {
      label: 'fallback pose',
      caption: '等待真实后端或离线遥测接管，这里先保留地图舞台、TF 叠层和路径占位的布局位置。',
      headingLabel: headingDeg,
      robotPercentX: x,
      robotPercentY: y,
      tone: 'warning',
    }
  }

  if (connection.mode === 'offline') {
    return {
      label: 'simulated pose',
      caption: '位置和朝向来自离线运动学回放，适合先做地图画布、TF 壳层和导航反馈布局。',
      headingLabel: headingDeg,
      robotPercentX: x,
      robotPercentY: y,
      tone: 'neutral',
    }
  }

  if (navigation.localization.ready) {
    return {
      label: 'amcl pose lock',
      caption: projected
        ? '真实 `/map`、`/tf`、`/amcl_pose` 和 Nav2 action status 已接入后端，机器人位姿正在投到真实地图坐标里。'
        : '真实 `/map`、`/tf`、`/amcl_pose` 和 Nav2 action status 已接入后端，这里优先显示定位层的稳定姿态。',
      headingLabel: headingDeg,
      robotPercentX: x,
      robotPercentY: y,
      tone: 'success',
    }
  }

  return {
    label: connection.robotOnline ? 'live odom pose' : 'stale live pose',
    caption: '真实链路已到位，但这里只负责地图舞台；后续直接在这里挂 `/map`、`/tf`、`/amcl_pose` 和 Nav2 叠层。',
    headingLabel: headingDeg,
    robotPercentX: x,
    robotPercentY: y,
    tone: connection.robotOnline ? 'success' : 'warning',
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function projectPoseToMapPercent(
  poseX: number,
  poseY: number,
  originX: number,
  originY: number,
  width: number,
  height: number,
  resolution: number,
) {
  if (width <= 0 || height <= 0 || resolution <= 0) {
    return null
  }

  const x = ((poseX - originX) / (width * resolution)) * 100
  const y = 100 - (((poseY - originY) / (height * resolution)) * 100)

  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null
  }

  return { x, y }
}
