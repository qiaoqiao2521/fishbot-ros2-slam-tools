# New-scene real FishBot autonomy

## Goal
User requested completing real-car mapping, navigation, obstacle avoidance and patrol from scratch in the changed scene. Simulation acceptance does not satisfy this task.

## Plan and acceptance
1. [partly complete] Both real boards connected; odom/scan/imu rates verified. Bounded motion response and active zero-command stopping measured. Firmware loss-of-command stopping and delayed-command rejection remain unverified; no unattended navigation acceptance.
2. [physical work paused; replacements implemented and isolated simulation acceptance passed 2026-10-06] User reports the car is charging. User explicitly chooses the official open FishBot geometry without a physical measuring prerequisite and authorizes items 2/3/4: continuous local tracking, graded clearance and trigger recording/replay. New opt-in Nav2/guard/replay tools implement these; the existing short-segment defaults remain intact. The saved real map remains incomplete. MuJoCo domain 96 passed continuous doorway traversal, hard-stop response and task cancellation; 74 focused tests passed. Baseline domain 93 and physical domain 0 were not operated. Native timestamps and heading-feedback consistency remain physical acceptance checks, not reasons to demand manual measurements again.
3. [pending] Transfer the measured SLAM pose to localization; validate real navigation and obstacle response with fresh sensors and actual motion evidence.
4. [pending] Complete and verify a multi-point patrol and return to its measured start. Preserve map, route, action results and stopping evidence locally.

Root Codex exclusively owns hardware commands and serial configuration. Workers may review or implement offline helpers; they must not independently operate the robot. Preserve healthy sensor listeners; restart only identified faulty receivers when necessary. A half-open TCP session was observed and the radar driver now expires idle TCP connections and accepts replacements.

## Knowledge adopted
Source: Obsidian Wiki/自动化开发范式与智能体协作, section 按当前任务选择验收依据. Judge this task by real hardware and scene evidence, not source tests, a running process or the previous MuJoCo result.
