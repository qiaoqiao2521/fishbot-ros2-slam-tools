# FishBot status — 2026-10-07

## Verified virtual behavior

- MuJoCo contact physics, wheel odometry, AMCL and Nav2 navigation passed the synthetic fixture.
- Web patrol visited three goals and returned home. Continuous passage control, collision-stop replay and bounded cancellation have separate simulation evidence.
- Visual inspection visited three stations, captured nine fresh RGB frames, classified green/red/empty and returned home in 73.703 seconds. Return XY error was 0.12287 m; stationary feedback passed. A deadline test confirmed cancellation and stopping.
- Pixel recognition is limited to the synthetic blue-frame indicator fixture. It does not establish general visual understanding or real camera availability.

## Real robot boundary

Historical live mapping and map/posegraph persistence passed locally. The latest real mapping session remains incomplete. Full doorway traversal, real Nav2 navigation and visual inspection remain unaccepted. Native timestamp consistency, actual rotation feedback and onboard stale-command/watchdog behavior require fresh hardware evidence.

No firmware was flashed and no hardware was operated by the repository connection. Do not infer physical acceptance from virtual results. Preserve command ownership, fresh odometry/scan checks and bounded stopping verification.

## Continue

- [Current project intent and priorities](PROJECT.md)
- [Visual inspection](docs/VISUAL_INSPECTION.md)
- [Continuous passage control](docs/PASSAGE_CONTROL.md)
- [Repository connection](docs/REPOSITORY.md)

Private operational notes and previous machine-specific status remain in the ignored local `.local/` backup. This update does not publish maps, posegraphs, provisioning details, captures or firmware backups. Already-published historical material remains in Git history.
