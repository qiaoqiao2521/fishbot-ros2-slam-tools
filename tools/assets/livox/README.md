# MID-360 angular-pattern subset

This directory reuses the official [Livox simulation CSV](https://github.com/Livox-SDK/livox_laser_simulation/blob/1cce1073633a062b92e30243a4c2920e45551bb5/scan_mode/mid360.csv), commit `1cce1073633a062b92e30243a4c2920e45551bb5` (2023-03-29), under the included MIT license. The upstream ROS Melodic/Gazebo 9 plugin is not loaded into MuJoCo/Jazzy.

`mid360-stride5.csv.gz` retains rows `0,5,10,...` and the original decimal azimuth/zenith strings, plus the original row index. It contains 160,000 of 800,000 rows. The CSV time column is not treated as seconds: the official plugin advances by row count. `mid360-source.json` records the source and derivation.

The native query adapter emits 4,000 rays per 10Hz frame. It advances by source time at a nominal 40,000 retained rays/s, based on the [official 200,000 first-return points/s specification](https://www.livoxtech.com/mid-360/specs) and 5x angular decimation. The finite CSV wraps every four source seconds. The actual retained elevation extent is approximately -7.2122 to +52.162 degrees; the product specification states -7 to +52 degrees. Angles are not clipped or relabelled into 16 uniform rings.

Limits: pose is frozen within each frame. There is no per-ray motion distortion, deskew, intensity, reflectivity/weather model, hardware range noise, physical IMU, or Livox Ethernet/UDP protocol. The task clips range to eight metres. This is a transparent MID-360-style angular simulation, not calibrated hardware equivalence.

## Manifest integration

Keep `scene_profile.sensors=lidar3d`. Pass `--lidar3d-config tools/config/cooperation_profiles/mid360-sensor.json` to the existing `cooperation prepare` command. The prepare entry reads the complete dictionary before native lidar/costmap configuration; it does not change the four-field scene-profile schema. Use `uniform16-sensor.json` through the same option to select the original uniform rings. Planar scenes ignore this optional setting with a warning; malformed optional JSON also warns and keeps the existing sensor.

The cooperation page keeps the 3D scan draft separate from the live combination. Download both `cooperation-profile.json` and `lidar3d-config.json`, and use the displayed prepare command. Downloading never changes or restarts the current runtime. The live scan label comes only from actual `state.lidar3d.scan_pattern`; older runtimes without it remain explicitly unreported.

Earlier cloud runs manually merged the complete dictionary into `manifest.lidar3d` before calling `cooperation_lidar.configuration(manifest)`. That was equivalent configuration, not proof that those runs used this later CLI. Existing `/sensors/lidar3d/points` and Nav2 voxel/collision-monitor consumers remain in use.

Do not label a default uniform 16-line manifest as MID-360. Copy this compressed asset, provenance JSON and license into cloud source bundles along with the Python module.

## Actual same-source comparison

Start this read-only observer after the original Factory instance is ready, using its domain and original planning Python/ROS environment:

```bash
python -B tools/cooperation_sensor_experience.py \
  --manifest "$scene/scene-manifest.json" --output "$run/sensor-experience" \
  --timeout 90 --frames 6 --separation-source-s 2
```

`frames` bounds the optional recording, not task execution. The observer creates no publishers or action/service writers. It matches received PointCloud2 + sensor metadata + physics by original scene/manifest identity, episode, sequence and nanosecond source stamp. Missing matches stay missing; no nearest pose is substituted. Ground-truth box wireframes come from an independent `mj_kinematics` query at that same pose; they are never sent into control.

Output contract: `sensor-experience.json` indexes `frame-N.json`. Each frame contains `identity`, `source_s`, actual `observed.points` in lidar XYZ metres, same-frame `truth.boxes[].vertices`, and actual same-stamp `actual_tf` when available. Use the same azimuth/elevation or 3D view for both layers. Non-box geometry is counted as omitted; truth includes occluded boxes. The record is not a photorealistic full-mesh reference.

The observer reports actual message counts, TF lookups and subscriber discovery, not per-message consumer ACKs. For Nav2 evidence, run the existing probe with `--allow-unorganized` and a known low-obstacle region. Preserve actual low-obstacle returns, TF, configured source and costmap lethal cells. Interface-only mode and endpoint discovery do not establish obstacle consumption or task success. The original Factory/Oracle owns the full delivery verdict.
