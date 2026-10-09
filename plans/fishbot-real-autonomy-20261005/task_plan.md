# New-scene real FishBot autonomy

## Goal
User requested completing real-car mapping, navigation, obstacle avoidance and patrol from scratch in the changed scene. Simulation acceptance does not satisfy this task.

## Plan and acceptance
2026-10-09: the user accepts the measured working map and later ends wireless
experiments. Unknown cells stay unknown. Fixed-map localization, outbound and a
resumed return passed with fresh stopping feedback. The first short patrol point
passed; its second was canceled and stopped. The user requested a larger continuous map route, then took over RViz goal
selection. The first closed route falsely completed in-place and remains failed
physical acceptance; the client now checks ordered intermediates and rejects
near-start endpoints. At explicit request, the running tolerant timing profile
uses 350 ms command/odom limits and short automatic zero-hold recovery. Preserve
collision, source identity and explicit operator stop. No extended quiet-clock
prerequisite is added; full physical route evidence is still required.

Filtered synchronization, leases, reconnect policy and resource rollback passed
offline/build checks. Sustained native freshness and repeated reconnection remain
unaccepted. Separately, host command-tail source ages of 259–262 ms triggered the
250 ms final gate during short-goal endings. Preserve both sets of evidence.

2026-10-08: the user placed the real car near the previous corner and requests resuming mapping until the accessible scene is covered. The current position must be localized against the measured saved graph; simulation-filled unknown space must not enter the real map. Preserve the computer's restored DHCP and VPN configuration. Restore both sensor streams first, verify native timestamps and stationary feedback, then resume supervised low-speed exploration with current scans and regular private checkpoints.

The user repaired a loose shaft coupler and requested another real test. Compare raw scans with native wheel odometry before accepting mechanical improvement. Straight and signed-turn tests now agree closely; a subsequent short Nav2 goal completed with fresh stopping feedback. Longer combined motion still needs calibration, and complete mapping remains pending.

Lower-left exploration reached two observation points with successful fresh stopping feedback. Short-delay current-TF prediction now supplies the local control chain; raw odom timestamps and original source gates remain unchanged. Same-source wheel pose/twist prediction is not independent fusion. The latest measured graph is saved privately. Repeated native clock drift still interrupts longer operation; restore stable source readiness before any further motion and retain incomplete full-scene coverage explicitly.

1. [partly complete] Both real boards connected; odom/scan/imu rates verified. Bounded motion response and active zero-command stopping measured. Firmware loss-of-command stopping and delayed-command rejection remain unverified; no unattended navigation acceptance.
2. [working map accepted by user; isolated simulation acceptance retained] On 2026-10-06, physical work paused while the car charged. User explicitly chooses the official open FishBot geometry without a physical measuring prerequisite and authorizes items 2/3/4: continuous local tracking, graded clearance and trigger recording/replay. New opt-in Nav2/guard/replay tools implement these; the existing short-segment defaults remain intact. The latest saved real map is accepted as the working-map baseline; unmeasured cells remain unknown. MuJoCo domain 96 passed continuous doorway traversal, hard-stop response and task cancellation; 74 focused tests passed. That simulation run did not operate baseline domain 93 or physical domain 0. After coupler repair, bounded real tests and another short continuous goal passed; native timing gates remain mandatory.
3. [outbound and resumed return complete] Fixed-map localization and Nav2 goals completed with fresh stopping feedback. Wheel return XY error was about 2.73 cm; this is not independent ground truth. Complete-route obstacle response remains unaccepted.
4. [pending physical acceptance] Continuous-route entry and false-success regression are implemented. Closed-route in-place result is rejected. User selects goals through RViz; tolerant profile is active with verified stationary readiness. Completed moving route, recovery and stopping still need actual evidence.

Root Codex exclusively owns hardware commands and serial configuration. Workers may review or implement offline helpers; they must not independently operate the robot. Preserve healthy sensor listeners; restart only identified faulty receivers when necessary. A half-open TCP session was observed and the radar driver now expires idle TCP connections and accepts replacements.

## Knowledge adopted
Source: Obsidian Wiki/自动化开发范式与智能体协作, section 按当前任务选择验收依据. Judge this task by real hardware and scene evidence, not source tests, a running process or the previous MuJoCo result.
