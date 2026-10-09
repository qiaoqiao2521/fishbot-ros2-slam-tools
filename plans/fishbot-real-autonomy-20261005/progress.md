# Progress

## Current: fixed-map navigation and continuous route, 2026-10-09

The user ended wireless experiments and confirmed USB was unplugged. After the
host restarted, root restored Agent, radar, sole fixed-map localization,
current-pose TF, Passage/Nav2 and RViz as identified detached processes. The
accepted graph remains private; unknown space was not synthesized for the car.

Outbound Nav2 completed with status 4/error 0 and fresh stationary feedback.
Live localization differed from the seed: the target was 45.44 cm from the
observed start, and raw wheel displacement was about 47 cm. Do not call this
a verified 25 cm move. Return attempt 1 canceled on an old-command latch;
stop acknowledgement, cancellation status 5 and fresh stationary feedback passed.
Return attempt 2 covered the remaining 22.27 cm and completed with status 4/error
0 and fresh stopping. Wheel XY return error was about 2.73 cm; no independent
physical-ground-truth measurement is available.

The first short patrol point completed. The second failed and canceled with
fresh stationary feedback; third and return were not sent. Two preliminary
attempts sent no goal because the guard was already latched. Root's offline
review matched host command-tail delays of 259–262 ms to the unchanged 250 ms
source limit. The smoother retains input stamps and has the same 250 ms timeout.
Native odometry was fresh in the matched captures. Do not attribute these
particular cancellations to the unresolved board-side UDP delivery delay.

The requested 3.05 m continuous closed route returned Nav2 status 4/error 0,
but the robot only rotated at the start. Raw net XY change was about 0.44 mm;
intermediate passage was not observed. Final XY equaled current XY, so the
controller satisfied its final goal check before traversing the path. The
original result remains private and is explicitly rejected by reassessment.
The helper now refuses endpoints within 0.1 m of the fresh start and requires
ordered, fresh map feedback within 0.15 m of each intermediate point.
No replacement route has been sent; full patrol remains unaccepted.

The user took over RViz goal selection. The configuration lacked SetGoal; root
added the 2D Goal Pose tool on `/goal_pose` and restored the visible RViz window.
Two map clicks reached Nav2, which planned and then failed to make progress.
The final gate still had an odom-age latch; later fresh feedback did not clear
that latch automatically. Root's requested fresh-zero reset succeeded.

The user then explicitly requested looser protection. Root applied the opt-in
`tolerant` timing profile: command/odom expiry 0.35 s, expired data immediately
outputs zero, stable health 0.2 s clears temporary timing holds, and only a new
candidate with post-recovery source time may move. A timing recovery window of
2 s includes the healthy confirmation; expiry becomes an explicit-reset latch.
Malformed/future data, ownership, CM invalid source, recording faults and
operator/task stop remain hard faults. Geometry and collision thresholds stayed
unchanged; strict remains the default for unselected runs.

Root stopped the guard and canceled navigation first (zero active canceling
goals). The launch supervises guard exit, so root restarted only Passage/Nav2,
retaining Agent, radar, localization, current TF and RViz. New launch PID 431328
uses timing_profile:=tolerant. Diagnostic readback confirmed both 0.35 s limits,
2 s window and 0.2 s recovery. Fresh-zero reset succeeded; native odom age was
1.77 ms, scan age 142.87 ms, v/w zero, and final publisher/subscriber ownership
was correct. No movement command or replacement goal was sent. Actual moving
recovery and completed tolerant-profile routes remain pending under user control.

A later readback observed a natural scan receive gap lasting beyond the
2 s recovery window, so tolerant mode correctly escalated to a persistent
scan-timeout latch. This shows the sensor delivery problem remains. Root
canceled navigation (zero canceling goals) and used fresh zero to reset after
feedback recovered. Final sample: guard healthy, native odom age 6.00 ms,
scan age 57.24 ms, v/w zero. No movement command was sent. Evidence:
`.local/clock-repair-20261009/tolerant-final-unlock.json`.

Current checks: 80 guard/goal/geometry checks passed, including actual Jazzy
message serialization. Earlier 41 firmware checks and application build remain
bound to unchanged firmware source. These do not repair the failed physical
source-freshness/reconnection acceptances or establish onboard anti-replay.

Private evidence: `.local/clock-repair-20261009/fixed-map-*-fast-*.json`,
`real-short-patrol-1/`, `continuous-route-live.json` and
`navigation-detached-runtime.json`, `real-continuous-route-1/reassessment.json`,
`tolerant-runtime.json` and `tolerant-ready.json`. Root owns configuration and
feedback inspection; the user owns RViz goal selection.
Knowledge closeout: `no_reusable_delta`; the adopted physical-evidence lesson
already applies, and the timing-tail finding belongs to this project.

## Earlier stationary clock repair, 2026-10-09

The accepted working map remains frozen. SLAM mapping and the odom TF predictor
were stopped before main-board application updates. Sensors and the final guard
remain available; no navigation goal is queued. The user moved the car near its
previous position while connecting USB. Fresh scan fitting produced a strong
localization seed, but live fixed-map localization has not started.

The identified motion board received application-only updates for periodic time
synchronization, clock lease expiry, automatic reconnect and resource teardown.
All 28 effective settings matched afterwards. Bootloader, partition table and
OTA data stayed unchanged; runtime NVS bytes differed without settings loss.
The private full backup and each unsuccessful acceptance attempt are preserved.

Three stationary Agent restarts recovered fresh native feedback in approximately
6, 9 and 12 seconds. This passed automatic reconnection only. Two subsequent
quiet intervals spanning more than 120 seconds failed sustained clock acceptance.
Odometry source ages reached 4.69 seconds and 2.51 seconds; radar ages remained
fresh, and host clock slew was only about 6–7 ms. No motion occurred.

Client 2.4.2 accepts late timestamp replies without matching their origin.
The application UDP filter is installed and independently checked against actual
SDK serialization, including the observed 28-byte INFO pong. The first filter
rejected that pong; the compatibility regression is fixed and retained as a test.
The subsequent quiet probe still failed: native age reached 3.64 seconds, with a
51.6-second receive gap and no motion. Raw UDP odometry was already seconds old
before Agent/DDS processing; source-clock error and transport delay are not fully
separated by that observation.

Valid ping replies at the host were followed by client session deletion. A single
100 ms connected ping failure can therefore cause repeated rebuilding. The current
application removes that independent teardown decision. Waiting-state discovery
ping, five-second filtered synchronization, the 15-second successful-sync lease
and 500 ms motor command timeout remain. Actual Agent source confirms unknown
clients receive no TIMESTAMP reply. Its restart test recovered the first cycle
in 14.88 seconds but failed the second cycle's readiness window. A quiet probe
then reached 2.42-second native age; a concurrent wire/DDS diagnostic reached
3.90 seconds. Those failures remain preserved, with no motion.

Passive physical-interface capture precisely matched 454 DDS stamps; NIC-to-DDS
delay was at most 5.14 ms. All 236 stale matched frames were already stale at NIC
ingress. Three TIMESTAMP requests arrived after the computer had already received
their board-side timeout logs, by approximately 50 ms, 3.20 seconds and 1.29
seconds. This confirms pre-NIC delivery delay, while transmit queues, radio and
AP remain unseparated. The Agent port 47138 is a network-byte-order print of 8888;
it does not establish NAT or socket recreation. Computer routes and VPN stayed
unchanged during these diagnostics.

Source review also found entity initialization errors logged and ignored before
unconditionally returning connected. The current application checks every
creation/add step and safely rolls back partial resources. Tests compile the
actual create/destroy functions and inject all 13 initialization-stage failures,
partial contexts, repeated rollback and retry. The 41 policy/lifecycle/filter
checks, independent review and PlatformIO build passed. New periodic UART fields
measure sync duration, UDP RSSI, actual Wi-Fi power-save state, configured maximum
transmit power, historical heap low-water mark and local UDP write duration.
Current-board acceptance remains incomplete.

With user approval, computer Wi-Fi power saving was disabled temporarily. Its
125-second probe still failed: maximum native age 4.317 seconds, 391 violations.
The original enabled state was restored and verified. A separate 125-second
probe with the radar receiver stopped also failed: maximum age 3.733 seconds,
475 violations. The receiver was restored with the correct workspace overlay,
and 20 fresh scans passed. Stopping this receiver does not exclude every source
of wireless contention. Computer IP, routes and VPN were preserved.

Application 8's diagnostic getters reported power saving disabled (PS=0, error=0).
Returned transport-write calls had interval maxima of 1.753–8.639 ms. This is a
local call duration, not over-air delivery time. The heap's historical minimum
fell from 110096 to 77672 bytes; this alone does not establish a leak. Its baseline
again failed: maximum native age 5.117 seconds, 435 violations and an 18.187-second
receive gap. Native poses and twist stayed zero. All 28 effective settings matched
before the next controlled experiment.

The source already requests WIFI_PS_NONE and uses best-effort odometry/IMU.
Priority 1 alone cannot establish starvation. Neither a long write call nor
the observed NIC delay uniquely identifies transmit-buffer congestion.
The stationary load comparison temporarily changed odom_pub_period from 50 to
200 ms. A post-startup requested readback confirmed all 28 target settings.
The 125.98-second observation failed: maximum native age 0.612 seconds and three
violations. It delivered only a 57.91-second odometry span, then no odometry for
the final 67.10 seconds. A smaller delivered-frame age is not continuous-readiness
acceptance. Native poses and twist stayed zero. The original 50 ms and all 28
effective settings were restored and confirmed by requested post-startup readback.

At that checkpoint, a near-AP stationary comparison was requested. The user
then confirmed the car was already 1–2 metres from the AP and ended further
experiments. The current navigation section supersedes that next action; the
failed source-freshness and reconnection acceptances remain preserved.
Private handoff: `.local/clock-repair-20261009/handoff-in-progress.json`.

Knowledge closeout: `no_reusable_delta`. The adopted physical-evidence lesson
still applies; SDK-specific findings and failed hardware probes stay in this
project. Root Codex owns the repair and subsequent real acceptance.

Preserved delivery exception: the untracked firmware release.sh is not a verified
release artifact. It references private legacy metadata and a boot_app0 image
whose merged-image provenance/layout is unverified. Root Codex owns follow-up:
check it against the pinned toolchain and actual partition/OTA layout before
execution or publication. Application-only builds and writes do not validate it.

## Working map accepted, 2026-10-09
The user accepts the latest measured map as the complete working map for this scene. Mapping scope is closed by that decision; unknown cells remain unknown. The accepted private checkpoint and pose graph are bound to SHA256 values in the local acceptance record. No new motion or firmware write occurred during acceptance.

Next: stabilize native clock alignment, switch to fixed-map localization, then verify an outbound route, return and fresh stopping feedback. Use the installed `slam_toolbox localization_launch.py` with explicit `mode: localization` and the accepted pose graph. Stop the mapping node before that switch. Only localization may publish map->odom; retain the existing Passage guard and source gates. Three-point patrol follows the single-route acceptance. Fixed-map navigation and patrol remain unaccepted.

Knowledge closeout: `no_reusable_delta`. This acceptance changes project scope; the existing physical-evidence lesson still applies. Root Codex owns clock stabilization and the subsequent real navigation acceptance.

## Measured lower-left exploration, 2026-10-08
The user redirected exploration to the lower-left corner. A 0.986 m map goal reached its first observation point and passed fresh stopping feedback. The next goal stopped partway on native odom timestamps in the future; cancellation and guard stop were acknowledged. Its immediate stationary acceptance failed, although later raw twist was zero.

A subsequent approximately 25 cm map goal reached the corner observation point and passed fresh stopping feedback. No movement goal remains queued. Complete scene coverage is still pending.

The latest measured lower-left raster has no reachable free-to-unknown boundary within the explored corner. Thin white rays beyond the west/south wall are disconnected from current free space. The latest scan does not establish a vehicle-width exit. This corner inspection can conclude without claiming complete scene coverage.

Direct raw odom2tf was stopped before enabling short-delay current-TF prediction. Raw odometry was not restamped, and native source freshness limits stayed intact. Stationary predicted/raw XY agreed and yaw differed by approximately 2.22e-16 rad; zero-input candidate age was P95 26.14 ms, maximum 26.22 ms. A separate 20 cm Nav2 goal passed action status 4/error 0 and fresh stopping feedback in 15.90 seconds.

These tests establish bounded control-chain operation. They do not establish independent sensor fusion or complete wheel calibration. Wheel pose and twist share one source.

The native clock later crossed the 50 ms future limit. The main-board restart service timed out, but odom reset to zero and a newly created XRCE session independently confirmed the restart. Native ages initially recovered to about -7..37 ms.

SLAM and the predictor were stopped before that reset; fresh scan fitting and the saved graph restored the map pose before another goal. No firmware, computer network, VPN or global NTP setting changed. The final stationary capture again contained native ages down to -56.9 ms, so another movement needs renewed source readiness. Repeated clock drift remains unresolved.

The private `lower-left-corner-checkpoint` contains nonempty PGM/YAML/posegraph/data. Nav2 map saving succeeded and graph serialization returned 0; the 108x119 map has about 7.408 m2 free and 9.648 m2 known. Earlier checkpoints and failed attempts remain preserved. The current stopped map pose is approximately (-0.331, -3.087, 3.591 rad). Original unknown cells remain unknown. RViz, sensors, restored SLAM and the current-TF predictor remain running; only the final guard owns /cmd_vel.

Knowledge closeout: `no_reusable_delta`. The adopted physical-evidence lesson remains applicable; the new results and unresolved vehicle-clock issue belong in project progress. Root Codex owns further timestamp stabilization, scene exploration and full-route acceptance. Private runtime handoff: `.local/real-network-20261008/progress.md`.

## After coupler repair
2026-10-08, after coupler repair: the user returned the car to the floor near the original opening. Native sensors and raw `odom2tf` recovered. This initial repair retest used no experimental predicted TF or restamped odometry. Fresh scans independently fitted the saved measured graph before SLAM resumed.

| Test | Independent raw-scan ICP | Native wheel odometry |
| --- | --- | --- |
| Stationary baseline | 1.06 mm, 0.014° | Zero change |
| Straight request, 10 cm | 9.39 cm forward, 0.40° yaw | 10.27 cm forward, 0.17° yaw |
| Left turn | +8.49° | +8.64° |
| Right turn | −8.21° | −9.03° |

Each bounded segment completed and passed five seconds of fresh stopping observation. ICP P80 residuals were 7.09–10.07 mm. Right-turn registration retained a secondary solution about 0.74° away. Mechanical agreement improved substantially; these short tests do not establish complete wheel calibration.

Zero-input timing through the full chain passed: candidate age P95 174 ms, maximum 199 ms, and explicit reset succeeded. A subsequent 25 cm Nav2 goal completed in 17.60 seconds, with action status 4, error 0 and fresh stationary feedback. Independent ICP measured 22.59 cm net displacement and +3.63° yaw; native odometry reported 24.73 cm and +6.21°. The remaining 2.58° yaw difference requires further calibration. Net displacement is neither cumulative path length nor a straight-line calibration.

Map saving succeeded and graph serialization returned 0. The new private `repaired-coupler-checkpoint` contains PGM/YAML and posegraph/data, about 7.22 m2 free and 9.20 m2 known. Original checkpoints and failed attempts remain preserved. No firmware, computer network or VPN setting changed. Full coverage, complete-route navigation and installed-board watchdog acceptance remain pending.

The accumulated Passage fixes passed 84/84 offline tests, including ROS message serialization. Root Codex owns further real mapping from fresh pose, scan, clock and stationary checks. No movement goal is queued. Private runtime and evidence handoff: `.local/real-network-20261008/progress.md`.

Knowledge closeout: `no_reusable_delta`. The adopted physical-evidence lesson remains applicable; this turn adds vehicle-specific repair and short-run measurements to project progress.

Preserved build work: `fishbot_motion_control_microros/release.sh` remains `pending`, owned by root Codex. Shell syntax passed and the selected application builds with pinned top-level dependencies. The legacy release path copies ignored provisioning configuration; boot_app0 provenance and merged-image layout remain unverified. Do not run that path until isolated validation and provisioning exclusion are complete. Current repair uses application-only writes.

## Earlier continuation before coupler repair
2026-10-08: both boards passed persistent server-setting readback and native odom/IMU/scan were received. Computer DHCP and VPN stayed unchanged. Two independent scans aligned to the original measured map within 1.6 mm and 0.16 degrees; the saved graph and live TF were restored. The first continuous real 10 cm goal completed with fresh stopping feedback. Independent ICP measured about 9.14 cm forward and 9.23° left yaw, versus 15.85° wheel yaw. A 30 cm goal stopped partway on collision prediction. Native Nav2 replay found an old local static-map cell on the current footprint. Disabling only that local layer cleared the footprint and remaining 9.22 cm sweep. Later goals stopped on time-transform failures or collision monitoring; a predicted-TF experiment was not accepted as wheel calibration. The last pre-repair serialized graph was `room-side-checkpoint`, about 7.24 m2 free and 9.12 m2 known. Those failures remain evidence; fresh source ages must pass before any further motion.

2026-10-06: user explicitly chooses the official open FishBot geometry without a measuring prerequisite and requests implementation of continuous local control, graded clearance and trigger recording/replay. The new opt-in pipeline and offline replay are implemented. Isolated MuJoCo domain 96 completed one continuous 1.25 m goal through a synthetic 36 cm doorway, including stationary feedback; real hardware was not operated while charging. The real 1 m/mapping task remains incomplete and its saved map/graph are preserved. Root owns later real sensor/time/heading and passage acceptance, without reintroducing a manual measurement gate. Detailed offline/simulation results follow below.
## Done
- Verified each board identity and changed only its computer-server address, with write acknowledgement and explicit stored readback. USB is now unplugged; no further USB action is required for mapping.
- Fixed radar timer allocation, half-open TCP/EOF recovery and variable scan-grid geometry in both source/delivery copies. Real scans, TF and SLAM are running in domain 0; MuJoCo domain 93 remains independent.
- Preserved previous map/pose-graph snapshots before SLAM geometry restart. Fresh maps are private under the chat work directory, never repository artifacts.
- Recovered MCU/host timestamp alignment by restarting only the micro-ROS agent. Wheel odometry survived that session renewal. Future/old native odom still aborts motion; no restamping workaround or global NTP change was applied.
- Segments 07 and 08 each completed 0.30 m and stopped, with five-second observation. expanded-08 saved successfully as PGM/YAML plus posegraph/data (serialize result=0). The 4.95×2.25 m canvas contains only about 3.35 square metres of free cells; the remainder is occupied or unknown.
- Offline connection/grid/guard regressions pass 34/34, including signed left/right turns. Firmware has not been flashed and its loss-of-command watchdog remains unverified.

## Remaining / next owner
Root Codex exclusively owns physical continuation. Start from the latest private checkpoint and fresh map TF, raw scan, native timestamps and stationary feedback. Preserve sensors and stop/snapshot on recurrence of timing failure. Do not mistake enlarged unknown canvas for large-scene coverage. Complete navigation and patrol remain pending until mapping and the installed-board stop/command-age boundary are accepted. Reassess actual clearance before movement; do not reduce protection simply to force passage.

Private runtime/evidence location: `local-only: work/real-20261005/`. Active receiver session: `fishbot-real-20261005`. Individual segment JSON files preserve completed/stopped separately; segments 04 and 05 have stopped=false due to freshness failure even though zero twist was separately observed. Do not overwrite those failures.

## Repository boundary
The canonical FishBot project now has the existing `qiaoqiao2521/fishbot-ros2-slam-tools` remote. The historical parent migration remains a separate Git boundary. Preserve its cross-project moves and compatibility links. Commit verified FishBot source changes from this project root. Maps, runtime logs, addresses/configuration and credentials must stay outside Git.

## Continuous-control delivery, 2026-10-06
- Implemented the user's selected items 2/3/4 using the official model: continuous NavigateToPose/RPP, shared model polygons with soft speed limits and hard collision stops, one stamped final command guard, and trigger JSON/RViz/offline replay. Usage: `docs/PASSAGE_CONTROL.md`. Physical measurement is not a prerequisite in this plan.
- Final focused suite: 74 tests passed (42 passage config/goal/replay, 28 command guard including real ROS message serialization, 4 isolated-domain boundary tests). Python/shell syntax and diff checks passed; selected MuJoCo package build passed.
- `sim-run04`: one continuous 1.25 m target crossed the synthetic 36 cm doorway and stopped, action status 4/error 0, total 42.777 s including discovery and final five-second observation. MuJoCo truth ended at x=1.222455 m, y=-0.005974 m. Maximum absolute lateral deviation was 1.787 cm. Main automatic slowdown lasted 10.43 s at at most 0.03 m/s. Final topic had only guard publisher and diff_drive_controller subscriber.
- Hard-stop trial: physical MuJoCo box injection plus a four-second upstream forward request produced VelocityStop; truth movement during that request was at most 1.232 mm. Actual saved scan/TF replay verified 353 valid transformed points; the saved upstream 0.0375 m/s input yields 41 points in the generated forward hard envelope, while the asynchronously recorded idle polygon has none. Seven invalid returns remain unknown. Exact CM-internal frame pairing is unavailable and clearly labelled.
- Integration found and fixed stale zero-tail messages incorrectly causing a permanent fault after reset. Such zero commands now remain idle with their original timestamp; stale nonzero/future/invalid commands still fail. `sim-run05` validated the final code's ten-second task deadline: stop service acknowledged, cancellation acknowledged, terminal status 5, stationary feedback true. Independent truth remained stopped at x=0.578084 m. Nav2 logged a child-result retrieval warning during halt; both navigation/controller cancellation and subsequent stationary truth were confirmed, so the warning is preserved rather than hidden.
- Output and failed attempts remain private under the chat's `work/review-20261006/`: successful passage and chart in `sim-run04/`, cancellation in `sim-run05/`, historical batch in `replay-final-v03/`, actual stop replay in `replay-sim-collision-stop-v2/`. No maps/scans/runtime logs enter the commit. The isolated simulation processes were shut down after checks; the charging car was not contacted.
- Next owner: root Codex. When the user resumes real operation, use the new opt-in pipeline with the saved SLAM state, verify current sensor native times and heading consistency, then accept actual passage/mapping. The firmware command-age/watchdog boundary remains unverified. Broader parent-repository migration work stays preserved for serial root review at the existing consolidation plan; no remote exists for a push.

## Final checkpoint for this run
- Segment 24 completed a -0.65 rad turn and stopped. Segment 25 requested 0.20 m but stopped after about 3.9 cm on `obstacle in forward stopping corridor`; stopped=true after 5.004 seconds of zero-command observation. No motion remains queued by this task.
- Across 27 recorded attempts, 21 completed and stopped; measured advance distance sums to 4.428 m. The remaining attempts include clearance stops, startup-sample / scan-timeout rejection and the two earlier timestamp-related stop-verification failures. These are retained, not relabelled successes.
- Final independent snapshot: zero linear/angular odom velocity, native odom age 18.3 ms, current map TF age 24.3 ms. The partial 99×111 map uses 0.05 m cells and contains about 5.798 m² classified free (about 7.195 m² known). Full large-scene coverage is not complete.
- Final occupancy map and serialized graph: private `maps/real-map-20261005-partial.{pgm,yaml,posegraph,data}`. Map saver reported success and serialize returned result=0. All files are nonempty; `FishBot-实车局部地图-20261005.zip` passed its ZIP integrity check and includes a current PNG plus final-state JSON.
- Main sensors/SLAM remain available; all bounded movement commands from this task finished. Root owns the next mapping session. The user reported limited battery; preserve the saved graph for continuation instead of repeating calibration sweeps. Real navigation, obstacle-avoidance autonomy and patrol remain pending.

## Continued session
- Root confirmed native odom/scan and stationary state before resuming. Segments 26/27 completed a small reposition; 28 stopped partway through a planned return turn on insufficient scan coverage, so its queued advances did not run.
- Original guard width is 0.54 m; raw scans showed a roughly 0.39–0.40 m opening. Official teaching-model wheel/body geometry gives 0.24 m width, while actual robot measurements remain unavailable. After explaining the assumption and receiving the user's direct assertion that the cleared car/path fit, root enabled the explicit standard-model profile for this passage: 0.18 m half-width and 0.03 m/s. Default conservative parameters, source-time freshness, 0.34 m forward length, 0.25 m rotation clearance and five-second stop observation remain unchanged.
- Startup now proceeds as soon as 30 fresh odom and 15 fresh scan samples are available, waiting at most 8 seconds. The previous fixed four-second wait occasionally rejected healthy late discovery. Existing data requirements are unchanged. Focused offline tests pass 40/40 after profile and startup-loop regressions.
- Segment 29-model stopped on scan coverage near the target heading. Its first finish attempt had insufficient startup samples and made no movement. After the startup fix, its remaining -0.22 rad turn passed. Segments 30-model and 31-model each advanced 0.10 m and stopped; segment 32-model then stopped after about 0.13 m on forward corridor clearance, with stopped=true. Runtime files explicitly record profile and model assumption. Check the newest segment JSON and live pose before further commands; never infer a completed turn from its requested amount.

## Live RViz handoff
- The latest user request was to open RViz for real-time viewing. Root opened the installed Jazzy RViz on the existing desktop X display in real ROS domain 0, with `/map`, best-effort `/scan` and `base_footprint` axes, fixed frame `map`. Config and launch script remain private: `real-live.rviz` and `rviz.sh`; tmux window `fishbot-real-20261005:rviz`. No navigation-goal/initial-pose tools were added to this viewing configuration.
- Verified the visible RViz window and rendered map/red laser points. Direct five-second subscription received 36 scans at 7.1065 Hz and 100 odom samples. Final odom was zero with 83.8 ms source age; command publisher list was empty. A ROS CLI daemon briefly reported zero scan publishers, but direct node discovery identified `fishbot_laser_driver_node` and fresh subscriptions proved the stream; do not diagnose from stale daemon metadata alone.
- New map checkpoint `maps/real-map-20261005-rviz-checkpoint` saved successfully, including serialized pose graph with result=0. Files are nonempty, and the saved PGM has about 6.665 m² free area. Prior checkpoints and ZIP remain preserved. Total odom-derived straight travel across recorded attempts is about 4.823 m; this is not an external physical-distance calibration.
- Next owner is root Codex. Continue from a fresh pose/scan check; segment 32-model did not reach its requested 0.30 m. Crossing the entire narrow opening remains unverified. Keep the standard-model assumption explicit, retain the conservative default, and use the live RViz view for scene feedback. There is no running movement command at this checkpoint; sensors, SLAM and RViz remain running.

## Latest passage continuation
- Recovery-only reverse mode and terminal turn deceleration are implemented; 47 offline tests pass. Every recorded command retains actual velocity values, profile and model assumption. Default collision widths, timestamp gates and five-second stopping observation remain unchanged.
- Segment 33 reversed 0.0685 m then stopped on native odom freshness. The motion-board reset restarted odom at zero. `passage-recovery-33` saved successfully before recovery; root paused measurements, restored the serialized graph with an approximate map-pose seed, resumed and verified live streams.
- Segment 34 completed another 0.0837 m reverse. Segment 35 requested +0.192 rad and measured +0.19284 rad in wheel odom; segment 36 advanced approximately 0.153 m. Both completed with stopped=true. These wheel-odom values are not independent body-motion calibration.
- New scans `after-34-scan.json`, `after-36-scan.json` and `after-36-settled-scan.json` remain in the private work directory. A minute of stationary waiting did not materially change the latter scene; host radar TCP receive queue was empty. This does not establish acquisition timestamps, but the proposed right-turn route must be recalculated rather than trusted from wheel odom.
- Root owns next action: incorporate the physical observation, verify live zero velocity and source freshness, then plan from current scan and validate actual body rotation after each bounded turn. Full passage, complete-scene mapping, real navigation and patrol remain unaccepted.

## Heading-control continuation
Small bounded advances and fresh scan checks brought the robot closer to the opening, but it is not across. Standard-model rotation clearance is now 0.20 m by the official model plus the existing margin; the conservative default remains 0.25 m. Opt-in heading hold has an additional all-direction clearance gate. The focused suite passes 53 tests. Segment 54 completed a short 4 cm request; segment 56 stopped on front clearance. All failures remain intact.

## Current-direction 1 m request checkpoint
- Segment 57 completed the last bounded alignment. The user then explicitly requested current-direction forward travel of 1 m with heading hold. Segment 58 was the first of four proposed 0.25 m segments; it stopped early on front clearance, so later queued segments did not execute. Its measured forward displacement was 0.04918 m, lateral displacement 0.000346 m, and native yaw change -0.1403 degrees; these are odometry values, not independently calibrated chassis accuracy.
- The stationary post-58 cloud showed about 1.48 m of continuous-wall forward clearance at heading zero, but only 3.2/4.9 mm outside the selected protection boundaries. A single guarded retry, segment 59, rejected the front corridor without additional displacement. No clearance threshold was reduced. The triggering scan was not recorded, so it cannot be classified as a false obstacle.
- Segment 58 has completed=false, stopped=true. Segment 59 has completed=false, stopped=false after 8.043 seconds of zero commands; preserve that failure. Independent after-59 capture showed unchanged pose and zero twist, with native timestamp ages ranging from -0.1055 to +0.0039 seconds. The subsequent map snapshot reported zero twist and source age -0.0146 seconds. Intermittent clock alignment remains a blocker for continuous fresh-feedback acceptance.
- Saved private `maps/requested-straight-1m-checkpoint.{pgm,yaml,posegraph,data}`: map saver succeeded, serialization result=0, all four files nonempty. The 99x117 occupancy map has approximately 6.725 m2 free and 8.4425 m2 known. `straight-1m-map-checkpoint.{json,png}` and `rviz-after-straight-request.png` preserve the latest visible state. Mapping, full passage and the requested 1 m are incomplete.
- Operator cleanup remains necessary for the earlier bounded tcpdump diagnostic: its timeout could not signal tcpdump because AppArmor denied signals from the agent's security label. Last verified diagnostic PID 150916 with parents 150915/150914. Root must not bypass AppArmor or kill its parents; the user can verify the exact process in an ordinary terminal and send it SIGINT. Private `diagnostic-cleanup.txt` contains the recovery steps. This diagnostic does not publish robot commands.
- Next owner: root Codex. Sensors, SLAM and RViz remain running; no motion is pending. Start from fresh source-time and point-cloud evidence, retaining the current direction request and model assumptions. The existing broad parent-repository migration handoff remains unchanged; no remote is configured.
