# FishBot public status — 2026-09-15

Local consolidation is reflected in this repository's source layout. The actual
network LiDAR driver, Agent sources and controller firmware source are included.

Historical live mapping and map/posegraph persistence were verified locally on
2026-09-11; this update does not publish those private room captures. A roughly
ten-second control delay remains unresolved. Posegraph restore/localization and
Nav2 acceptance remain unverified.

This is source/layout and offline-test evidence, not new hardware acceptance.
Do not start floor motion until odometry/scan/TF freshness and latency are verified.
Firmware safety changes are source-only and have not been flashed by this publication.
