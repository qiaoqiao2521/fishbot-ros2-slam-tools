import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { NavGoalShell } from '@/components/navigation/nav-goal-shell'
import { TaskStatusShell } from '@/components/navigation/task-status-shell'

export function ExpansionPanel() {
  return (
    <Card>
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">mission handoff / queue choreography / action wire-up</div>
          <CardTitle>Navigation / Task Controls</CardTitle>
          <CardDescription>
            把 goal queue、取消/清空动作和任务状态卡先固定下来，后面接真实导航回执时可以直接替换数据源。
          </CardDescription>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <NavGoalShell />
        <TaskStatusShell />
      </div>
    </Card>
  )
}
