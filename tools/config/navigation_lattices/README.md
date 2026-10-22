# Native differential lattice

`diff-r060-2cm.json` is generated with the unmodified Nav2 1.3.13
[official generator](https://github.com/ros-navigation/navigation2/tree/1.3.13/nav2_smac_planner/lattice_primitives).
The generator is Copyright (c) 2021, Matthew Booker, Apache-2.0.
The upstream repository notice is retained in `LICENSE.nav2`; the full
Apache-2.0 text is retained in `LICENSE.Apache-2.0`.
The editable generator input is `diff-r060-2cm.generator.json`.

The model is differential, with a 0.60 m curve radius and 0.02 m grid.
It includes forward trajectories and in-place rotations, without sideways motion.
Do not substitute the installed 0.05 m sample for the existing 0.02 m costmap.

From the official generator directory, use an environment containing its
declared NumPy, Matplotlib and Rtree dependencies:

```bash
python3 generate_motion_primitives.py \
  --config /path/to/diff-r060-2cm.generator.json \
  --output /path/to/diff-r060-2cm.json \
  --visualizations /path/to/primitive-plots
```

Pass an alternative generated file through `prepare --lattice-filepath PATH`.
Preparation copies it into the independent scene. It does not mutate the active planner.
Matching metadata does not establish path, controller or physical transport acceptance.

## Nav2 1.3.13 transition cache

The installed native library can reuse endpoint validity for a colliding incoming
primitive. `cooperation_lattice_cache_probe` reproduces this with a clear endpoint
and a blocked straight edge; no actions are sent.

The scoped fix is `tools/patches/nav2-1.3.13-lattice-edge-cache.patch`.
Apply it to the official 1.3.13 `nav2_smac_planner` source and build that package
in an independent overlay. Headers and public ABI remain unchanged.
Use the existing `FISHBOT_NAV2_QUERY_OVERLAY=<overlay>/install` launch hook.
The system installation and other running instances remain unchanged.

Run the same native probe with `cached` against the original installation and
`fixed` against the overlay. The fixed probe must reject both cold and cached
blocked transitions. A manifest records this prerequisite; it does not claim
that the running library was patched. Verify actual loaded paths separately.

For a new scoped overlay, clone the exact upstream tag, apply the patch, and
build only `nav2_smac_planner`. Run from the FishBot project root:

```bash
task_nav2_root="$HOME/.cache/fishbot/nav2-lattice-1.3.13"
git clone --depth 1 --branch 1.3.13 \
  https://github.com/ros-navigation/navigation2.git "$task_nav2_root/src/navigation2"
git -C "$task_nav2_root/src/navigation2" apply --directory=nav2_smac_planner \
  "$PWD/tools/patches/nav2-1.3.13-lattice-edge-cache.patch"
source /opt/ros/jazzy/setup.bash
CMAKE_BUILD_PARALLEL_LEVEL=2 colcon --log-base "$task_nav2_root/log" build \
  --base-paths "$task_nav2_root/src/navigation2/nav2_smac_planner" \
  --build-base "$task_nav2_root/build" --install-base "$task_nav2_root/install" \
  --packages-select nav2_smac_planner --allow-overriding nav2_smac_planner \
  --cmake-args -DBUILD_TESTING=OFF -DPython3_EXECUTABLE=/usr/bin/python3
```

This source build was exercised with Jazzy 1.3.13 in a separate cache workspace.
It does not replace `/opt/ros/jazzy`. The full upstream checkout method above
is an alternative to the package-only source download used for that build.

Build the small native reproducer independently:

```bash
cmake -S tools/cooperation_plan_witness -B "$task_nav2_root/probe-build"
cmake --build "$task_nav2_root/probe-build" --target cooperation_lattice_cache_probe -j2
"$task_nav2_root/probe-build/cooperation_lattice_cache_probe" \
  "$PWD/tools/config/navigation_lattices/diff-r060-2cm.json" cached
source "$task_nav2_root/install/local_setup.bash"
"$task_nav2_root/probe-build/cooperation_lattice_cache_probe" \
  "$PWD/tools/config/navigation_lattices/diff-r060-2cm.json" fixed
```

An original-library reproducer exit of zero means the bug was reproduced.
Only the fixed result means both blocked transitions were correctly rejected.
The reproducer sends no motion goals and uses its own small diagnostic footprint.

## Path tracking boundary

The default differential file includes in-place rotations. Native RPP with
`allow_reversing=true` cannot enable its own `use_rotate_to_heading` simultaneously.
Planner reverse expansion and RPP reverse support therefore do not establish
execution of every zero-translation rotation in the path. Check actual commands,
physical displacement, goal outcome and the original task score separately.
Do not promote a planner-only or empty-tray result into loaded delivery acceptance.

`prepare --lattice-rotation-shim` explicitly wraps the transport RPP in native
`nav2_rotation_shim_controller::RotationShimController`. It uses path orientations,
one grid cell for initial heading sampling, and the original heading threshold.
RPP retains its parameter namespace and task-scoped limit/restoration transaction.
Staging keeps its original RPP. This option is not enabled by default.
The original-B tests with this wrapper still exceeded 120 seconds; it is not a
qualified J100 delivery preset.
