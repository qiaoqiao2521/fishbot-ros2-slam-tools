# robot_base in FishBot

Canonical maintenance is this package in `qiaoqiao2521/fishbot-ros2-slam-tools`.
There is no nested Git repository or runtime dependency on the old checkout.

Origin: <https://github.com/muqiao215/robot_base>, base commit `77d1ba2`.
License: Apache-2.0; the original LICENSE is preserved here.
Original authorship and repository remain part of the provenance.

The import includes reviewed September 11 local fixes: serial locking, bounded
receive buffers, reconnect-zero, command watchdog, configurable serial settings,
finite feedback, odometry covariance, and portable launch/package metadata.
The original uncommitted checkout remains untouched for recovery.

FishBot combines repeated drive/TF launches and adds a scoped build/launch entry.
The serial protocol and wheel order remain unchanged. No map, session state,
old build, hardware exercise script, or placeholder lint test was imported.
Existing navigation parameters remain a legacy baseline.

The PTY regression exposed a legacy reconnect gap. FishBot also enables speed
feedback when reconnecting through the command-send path, preserving reconnect-zero.

This import does not certify physical calibration, holonomic Nav2 performance,
MuJoCo mecanum contacts, cargo handling, or sim-to-real transfer.
