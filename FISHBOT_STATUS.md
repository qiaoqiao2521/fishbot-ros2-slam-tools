# FishBot status — 2026-10-11

## Current real work

The user has sold the physical car and explicitly accepts mapping and navigation
as complete for this project stage. Physical work is closed. Do not schedule
another power-on, firmware update, passage test or patrol on that vehicle.
Keep the private map, code and simulation assets for reuse.

This closure does not rewrite failed historical trials or establish additional
production, moving-recovery or physical-inspection acceptance. The latest task
retrieves user feedback through TraceMesh and updates the existing knowledge
page; it operates no hardware.

## Historical physical checkpoints

The user accepted the latest measured checkpoint as this scene's working map. Mapping is closed; unmeasured cells remain unknown. The accepted raster and pose graph are frozen privately by hashes.

After coupler repair, independent scan registration and wheel odometry agreed closely in bounded straight/turn trials. Short Nav2 goals and five seconds of fresh stationary feedback passed. This does not establish full calibration or complete-route navigation.

The user ended further wireless experiments and requested real navigation under the existing source and collision gates. Following a host restart, sensors, fixed-map localization, Nav2 and RViz were restored. One outbound goal completed; its actual displacement was about 47 cm because live localization differed from the offline seed. Return first stopped on a command-age latch, then a remaining 22 cm goal completed. Both successful goals passed fresh stationary feedback. Wheel odometry ended about 2.73 cm from its pre-route origin; this is not independent physical accuracy.

A short patrol reached its first point; its second was canceled and stopped. A later 3.05 m through-poses action reported success, but the car only turned at its start: final XY equaled start XY, allowing early goal-checker success. This is a failed physical-route acceptance. The client now rejects endpoints within 10 cm of the fresh start and requires ordered fresh intermediate-pose feedback. Full patrol remains unaccepted.

RViz's missing 2D Goal Pose tool was added, and its map clicks reached Nav2. Those goals failed to make progress because an odometry-age latch still blocked output. The initial historical tolerant deployment used 350 ms command/odom expiry, immediate zero on expired data, 200 ms healthy recovery before new commands, and a two-second recovery window before a persistent timing lock. Its diagnostics and 80 related offline checks are historical evidence. The final deployed policy removed that escalation: ordinary expired/future timestamps, stream gaps, temporary TF failures and CM invalid source pause at zero and recover after 200 ms of healthy sources plus a new post-recovery command. Ownership conflicts, malformed data, nonfinite clocks, recording faults and operator stop still require explicit reset. Static footprint and collision limits are unchanged. This policy change does not establish moving-fault recovery acceptance or repair the board-side delivery failure.

Main-board application updates preserved all 28 effective settings. Filtered synchronization, clock leases, connected-session heartbeat, resource rollback and wireless diagnostics passed 41 host checks and the actual firmware build. Sustained native freshness still failed, including a 5.12-second age and a separate 67.10-second receive gap. Original computer power saving, 20 Hz publication and radar reception were restored. Those failures are retained; continuous clock, reconnection and onboard command-protocol acceptance remain pending. See [firmware clock repair](docs/FIRMWARE_TIME_SYNC.md) and [real task progress](plans/fishbot-real-autonomy-20261005/progress.md).

## Verified virtual behavior

- MuJoCo contact physics, wheel odometry, AMCL and Nav2 navigation passed the synthetic fixture.
- Web patrol visited three goals and returned home. Continuous passage control, collision-stop replay and bounded cancellation have separate simulation evidence.
- Visual inspection visited three stations, captured nine fresh RGB frames, classified green/red/empty and returned home in 73.703 seconds. Return XY error was 0.12287 m; stationary feedback passed. A deadline test confirmed cancellation and stopping.
- Pixel recognition is limited to the synthetic blue-frame indicator fixture. It does not establish general visual understanding or real camera availability.

## Historical acceptance boundary

Historical live mapping and map/posegraph persistence passed locally. Working-map acceptance does not establish measured coverage of every unknown area. Saved records did not establish full patrol, moving source-fault recovery, physical visual inspection or onboard stale-command/watchdog acceptance. These are archived limits, not pending operations on the sold vehicle. The user has accepted mapping/navigation completion within this stage's scope.

The 2026-10-07 repository connection itself flashed no firmware and operated no hardware. Subsequent real work is recorded above. Do not infer physical acceptance from virtual results. Preserve command ownership, fresh odometry/scan checks and bounded stopping verification.

## Continue

- [Current project intent and priorities](PROJECT.md)
- [Visual inspection](docs/VISUAL_INSPECTION.md)
- [Continuous passage control](docs/PASSAGE_CONTROL.md)
- [Repository connection](docs/REPOSITORY.md)

Private operational notes and previous machine-specific status remain in the ignored local `.local/` backup. This update does not publish maps, posegraphs, provisioning details, captures or firmware backups. Already-published historical material remains in Git history.
