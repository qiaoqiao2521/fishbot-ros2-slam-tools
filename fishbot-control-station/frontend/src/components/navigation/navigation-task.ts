import { getModePresentation } from '@/lib/station-runtime'
import type { ConnectionSnapshot, NavigationSnapshot, RobotStateSnapshot } from '@/types/station'

type Tone = 'neutral' | 'success' | 'warning' | 'danger'

export type NavigationActionPreview = 'idle' | 'cancel-active' | 'clear-queue'

export type NavigationQueueItem = {
  slot: string
  title: string
  source: string
  state: string
  detail: string
  tone: Tone
}

export type NavigationTaskCard = {
  title: string
  value: string
  hint: string
  tone: Tone
}

export type NavigationTaskPresentation = {
  modeLabel: string
  modeSummary: string
  modeDetail: string
  actionLabel: string
  actionHint: string
  cancelDisabled: boolean
  clearDisabled: boolean
  operatorNote: string
  queueItems: NavigationQueueItem[]
  taskCards: NavigationTaskCard[]
}

export function getNavigationTaskPresentation(
  connection: ConnectionSnapshot,
  robotState: RobotStateSnapshot,
  navigation: NavigationSnapshot,
  usingFallbackData: boolean,
  actionPreview: NavigationActionPreview = 'idle',
): NavigationTaskPresentation {
  const mode = getModePresentation(connection, usingFallbackData)
  const rateLabel = robotState.messageRateHz == null ? '未测量' : `${robotState.messageRateHz.toFixed(1)} Hz`
  const updatedAtLabel = new Date(robotState.lastUpdatedAt).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })

  if (mode.label === 'fallback snapshot') {
    return {
      modeLabel: mode.label,
      modeSummary: mode.summary,
      modeDetail: mode.detail,
      actionLabel: 'preview only',
      actionHint: 'buttons stay disabled until the backend stream replaces the fallback snapshot.',
      cancelDisabled: true,
      clearDisabled: true,
      operatorNote: 'This is a navigation/task skeleton. It keeps the layout and state vocabulary ready, but it does not claim real goal dispatch.',
      queueItems: [
        queueItem('1', 'Primary goal', 'ui scaffold', 'preview blocked', 'waiting for backend stream', 'warning'),
        queueItem('2', 'Next goal', 'ui scaffold', 'waiting backend', 'not dispatchable yet', 'warning'),
        queueItem('3', 'Standby goal', 'ui scaffold', 'read-only preview', 'safe layout only', 'neutral'),
      ],
      taskCards: [
        taskCard('Source of truth', 'front-end preview', 'no live state attached yet', 'warning'),
        taskCard('Dispatch path', 'blocked', 'wait for action wiring', 'warning'),
        taskCard('Queue policy', 'read-only', 'cancel / clear remain disabled', 'neutral'),
        taskCard('Freshness', `${updatedAtLabel} / ${rateLabel}`, 'snapshot only, not live telemetry', 'neutral'),
      ],
    }
  }

  if (mode.label === 'offline simulator') {
    return {
      modeLabel: mode.label,
      modeSummary: mode.summary,
      modeDetail: mode.detail,
      actionLabel:
        actionPreview === 'cancel-active'
          ? 'cancel preview'
          : actionPreview === 'clear-queue'
            ? 'clear preview'
            : 'local preview active',
      actionHint:
        actionPreview === 'idle'
          ? 'buttons update the local scaffold only, not the robot.'
          : 'the preview is local; wire it to goal services later.',
      cancelDisabled: false,
      clearDisabled: false,
      operatorNote: 'Offline mode is the safe place to design queue flow, cancel semantics, and status cards without pretending that Nav2 is already bound.',
      queueItems: offlineQueueItems(actionPreview),
      taskCards: [
        taskCard('Source of truth', 'simulated telemetry', 'robot state is replayed by the backend', 'neutral'),
        taskCard('Dispatch path', 'preview + local state', 'goal buttons are scaffold-only', 'neutral'),
        taskCard('Queue policy', 'cancel / clear local', 'changes stay in the frontend preview', 'success'),
        taskCard('Freshness', `${updatedAtLabel} / ${rateLabel}`, 'driven by the offline simulator', 'neutral'),
      ],
    }
  }

  return {
    modeLabel: mode.label,
    modeSummary: mode.summary,
    modeDetail: mode.detail,
    actionLabel:
      actionPreview === 'cancel-active'
        ? 'cancel preview'
        : actionPreview === 'clear-queue'
          ? 'clear preview'
          : 'wiring ready',
    actionHint:
      actionPreview === 'idle'
        ? 'still a skeleton until goal services and cancel acknowledgements are attached.'
        : 'preview only; the real action client is not wired in yet.',
    cancelDisabled: false,
    clearDisabled: false,
      operatorNote:
      'Live telemetry is present, but this remains a skeleton. Wire the action client, cancel feedback, and queue acknowledgements before calling it a real nav panel.',
    queueItems: liveQueueItems(actionPreview),
    taskCards: [
      taskCard('Source of truth', navigation.localization.ready ? 'amcl + nav status' : 'rosbridge telemetry', 'live robot data is flowing', 'success'),
      taskCard('Dispatch path', `${navigation.navStatus.activeGoals} active / ${navigation.navStatus.totalGoals} tracked`, 'bind the action client next', 'success'),
      taskCard('Queue policy', 'operator confirm', 'keep cancel / clear explicit', 'warning'),
      taskCard('Freshness', navigation.navStatus.ready ? navigation.navStatus.statusSummary : `${updatedAtLabel} / ${rateLabel}`, 'coming from live robot state', 'neutral'),
    ],
  }
}

function offlineQueueItems(actionPreview: NavigationActionPreview): NavigationQueueItem[] {
  if (actionPreview === 'cancel-active') {
    return [
      queueItem('1', 'Primary goal', 'local preview', 'cancel requested', 'active item marked for cancel preview', 'warning'),
      queueItem('2', 'Next goal', 'local preview', 'held during cancel', 'queue stays local until reset', 'neutral'),
      queueItem('3', 'Standby goal', 'local preview', 'waiting reset', 'safe preview state', 'neutral'),
    ]
  }

  if (actionPreview === 'clear-queue') {
    return [
      queueItem('1', 'Primary goal', 'local preview', 'queue cleared', 'local queue preview emptied', 'success'),
      queueItem('2', 'Next goal', 'local preview', 'queue cleared', 'held as empty placeholder', 'neutral'),
      queueItem('3', 'Standby goal', 'local preview', 'queue cleared', 'held as empty placeholder', 'neutral'),
    ]
  }

  return [
    queueItem('1', 'Primary goal', 'local preview', 'staged', 'ready to become the active target', 'neutral'),
    queueItem('2', 'Next goal', 'local preview', 'queued', 'the next waypoint waits here', 'neutral'),
    queueItem('3', 'Standby goal', 'local preview', 'standby', 'nothing has been sent to the robot', 'neutral'),
  ]
}

function liveQueueItems(actionPreview: NavigationActionPreview): NavigationQueueItem[] {
  if (actionPreview === 'cancel-active') {
    return [
      queueItem('1', 'Primary goal', 'operator input', 'cancel requested', 'preview only, not a live cancel ack', 'warning'),
      queueItem('2', 'Next goal', 'operator input', 'held', 'waiting for cancel wiring', 'neutral'),
      queueItem('3', 'Standby goal', 'operator input', 'standby', 'ready once the action client lands', 'neutral'),
    ]
  }

  if (actionPreview === 'clear-queue') {
    return [
      queueItem('1', 'Primary goal', 'operator input', 'queue cleared', 'preview only, not a live clear ack', 'success'),
      queueItem('2', 'Next goal', 'operator input', 'queue cleared', 'queued items are just placeholders', 'neutral'),
      queueItem('3', 'Standby goal', 'operator input', 'queue cleared', 'still a scaffold state', 'neutral'),
    ]
  }

  return [
    queueItem('1', 'Primary goal', 'operator input', 'dispatch ready', 'first goal slot is ready for wiring', 'success'),
    queueItem('2', 'Next goal', 'operator input', 'queued', 'the next stop will sit here', 'neutral'),
    queueItem('3', 'Standby goal', 'operator input', 'standby', 'local preview only until the action client is attached', 'neutral'),
  ]
}

function queueItem(
  slot: string,
  title: string,
  source: string,
  state: string,
  detail: string,
  tone: Tone,
): NavigationQueueItem {
  return { slot, title, source, state, detail, tone }
}

function taskCard(title: string, value: string, hint: string, tone: Tone): NavigationTaskCard {
  return { title, value, hint, tone }
}
