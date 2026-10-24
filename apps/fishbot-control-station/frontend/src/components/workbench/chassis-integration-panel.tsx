import { ArrowUpRight, Truck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardTitle } from '@/components/ui/card'
import type { AppRoute } from '@/lib/app-route'

export function ChassisIntegrationPanel({ onNavigate }: { onNavigate: (route: AppRoute) => void }) {
  return <Card id="workbench-chassis" className="workbench-chassis" aria-labelledby="workbench-chassis-heading">
    <div className="workbench-section-heading"><div><CardTitle id="workbench-chassis-heading">底盘接入，共用一套工作台</CardTitle><p>标准指令、里程计、地图与任务接口共用；运动学和验收按车型保留。</p></div><Truck size={21} aria-hidden="true" /></div>
    <div className="workbench-chassis-grid">
      <article data-chassis="fishbot"><h3>FishBot</h3><span>差速 · MuJoCo</span><p>原建图导航、固定工位运输与历史评分继续保留。</p><Button variant="outline" size="sm" onClick={() => onNavigate('cooperation')}>打开车臂页</Button></article>
      <article data-chassis="jackal_j100"><h3>Jackal J100</h3><span>四轮滑移转向 · 3D 雷达</span><p>完整 K 的 B→A 仿真已通过；路线时间余量与保护辅助单列。</p><a href="#workbench-delivery-timing">查看配送耗时</a></article>
      <article data-chassis="robot_base_mecanum"><h3>麦克纳姆 · robot_base</h3><span>ROS 底盘已合并 · 仿真模型待接入</span><p>串口驱动、横移、轮速里程计、TF 与 SLAM/Nav2 启动文件统一维护。伪终端验证不代表实车或完整运输。</p>
        <code>./fishbot.sh mecanum info</code><a href="https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools/blob/main/docs/MECANUM.md" target="_blank" rel="noopener noreferrer">接入与构建说明<ArrowUpRight size={13} aria-hidden="true" /></a></article>
    </div>
    <p className="workbench-chassis-note">麦克纳姆旧导航的横向速度上限为 0；自主横移和 MuJoCo 接触/载货模型仍待验收。本面板不连接或启动车辆。</p>
  </Card>
}
