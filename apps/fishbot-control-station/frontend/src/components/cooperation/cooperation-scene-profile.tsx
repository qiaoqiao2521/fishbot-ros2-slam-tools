import { useState } from 'react'
import { Download } from 'lucide-react'
import {
  COOPERATION_PREPARE_COMMAND, DEFAULT_COOPERATION_SCENE_PROFILE,
  SCENE_SENSOR_LABELS, SCENE_TASK_LABELS, SCENE_VEHICLE_LABELS,
  cooperationLiveProfile, cooperationSceneProfileHref,
  type CooperationProfileState, type CooperationSceneProfile,
} from '@/lib/cooperation-scene-profile'
import './cooperation-scene-profile.css'

type Props = { state: CooperationProfileState | null; draft: CooperationSceneProfile; onDraftChange: (value: CooperationSceneProfile) => void }

export function CooperationSceneProfileView({ state, draft, onDraftChange }: Props) {
  const live = cooperationLiveProfile(state)
  return <section className="cooperation-profile-panel" aria-labelledby="cooperation-profile-heading">
    <div className="cooperation-profile-live" data-scene-profile-kind="live">
      <h2>当前运行组合</h2>
      {live.reported ? <dl><div><dt>车型</dt><dd>{live.vehicleName}</dd></div>
        <div><dt>传感器</dt><dd>{live.sensorsLabel}</dd></div><div><dt>任务</dt><dd>{live.taskLabel}</dd></div></dl> : null}
      <p>{live.note}</p>
    </div>
    <div className="cooperation-profile-draft" data-scene-profile-kind="draft">
      <h2 id="cooperation-profile-heading">新场景配置草稿</h2>
      <p>选择后下载 JSON。这里只准备配置，不修改当前场景、不派发任务。</p>
      <div className="cooperation-profile-fields">
        <label htmlFor="cooperation-draft-vehicle">车型<select id="cooperation-draft-vehicle" value={draft.vehicle}
          onChange={(event) => onDraftChange({ ...draft, vehicle: event.target.value as CooperationSceneProfile['vehicle'] })}>
          {Object.entries(SCENE_VEHICLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label htmlFor="cooperation-draft-sensors">传感器<select id="cooperation-draft-sensors" value={draft.sensors}
          onChange={(event) => onDraftChange({ ...draft, sensors: event.target.value as CooperationSceneProfile['sensors'] })}>
          {Object.entries(SCENE_SENSOR_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label htmlFor="cooperation-draft-task">任务<select id="cooperation-draft-task" value={draft.task}
          onChange={(event) => onDraftChange({ ...draft, task: event.target.value as CooperationSceneProfile['task'] })}>
          {Object.entries(SCENE_TASK_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
      </div>
      {draft.task === 'three_batch_transport' && <p className="cooperation-profile-owner-note">三批 A / A / B 由现有 workflow 执行。网页不重复派发每批运输。</p>}
      <a className="cooperation-button cooperation-quiet cooperation-profile-download"
        href={cooperationSceneProfileHref(draft)} download="cooperation-profile.json"><Download size={15} aria-hidden="true" />下载场景配置 JSON</a>
      <details><summary>创建新独立实验的命令</summary>
        <p>在项目目录使用已配置的 FISHBOT_COOP_PYTHON。替换配置路径和 NEW_SCENE，输出目录须为新目录。</p>
        <pre>{COOPERATION_PREPARE_COMMAND}</pre>
        <p>此命令只准备场景。启动时选择独立 ROS 域、API 端口和运行目录；不会热替换当前实验。</p>
        <p><a href="https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools/blob/main/docs/COOPERATION_WORKFLOW.md" target="_blank" rel="noreferrer">完整启动与三批任务说明</a>：继续使用现有 workflow 初始化账本、接收就绪事件并运行任务。</p>
      </details>
    </div>
  </section>
}

export function CooperationSceneProfilePanel({ state }: { state: CooperationProfileState | null }) {
  const [draft, setDraft] = useState<CooperationSceneProfile>({ ...DEFAULT_COOPERATION_SCENE_PROFILE })
  return <CooperationSceneProfileView state={state} draft={draft} onDraftChange={setDraft} />
}
