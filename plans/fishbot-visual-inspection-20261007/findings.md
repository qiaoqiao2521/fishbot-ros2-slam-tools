# Findings

- Existing arena camera is viewer-only. The current model disables automatic camera registration.
- Domain 93 has a previously accepted navigation/patrol baseline. Passage acceptance uses domain 96. This task uses 97.
- Existing stamped Nav2 → smoother → Collision Monitor → diff-drive chain and AMCL can serve the new scene.
- Parent Git is `<historical-parent-repository>`; it has no remote. Preserve the broad preexisting migration changes and independent nested repositories.
- Results and renders remain in ignored/local run directories. Commit implementation and concise measurements, not runtime logs.
- CameraPlugin 0.1.1 reads the exact `mujoco_plugins.mujoco_camera_plugin` namespace. It supports EGL offscreen rendering and stamps RGB from the simulation snapshot. Source: https://github.com/ros-controls/mujoco_ros2_control/blob/0.1.1/mujoco_ros2_control_plugins/src/camera_plugin.cpp
- Image classification must inspect the full verified panel interior; inspecting only its center could mistake a lamp near the edge for an empty panel. The regression suite covers this case.
- An action server can be discoverable before the navigation lifecycle becomes ACTIVE. Initial dispatch waits for both.
- Process cleanup must check the owned process group, even if its launch parent has exited. Runtime scripts must not be edited during execution.
