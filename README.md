# FishBot ROS2 SLAM Tools

FishBot ROS2 SLAM Tools is a public snapshot of the WSL2/ROS2 helper scripts and control-station UI used to bring up a FishBot mobile robot for native ROS2 laser scan, odometry, SLAM, and map-saving experiments.

## What Is Included

- `ros2-tools/`: staged FishBot startup, preflight, teleop, laser probe, map probe, and map-save scripts.
- `fishbot-control-station/`: backend/frontend control station source.
- `fishbot-nav-src/`: FishBot ROS2 navigation, description, bringup, Cartographer, and YDLiDAR source snapshot.

## Current Boundary

The recommended workflow is native ROS2 mapping first. Do not treat frontend map rendering or one-click stack startup as proof that mapping is stable. A valid mapping session requires fresh `/scan`, fresh `/odom`, valid TF, and a real `/map` in RViz.

## Typical Flow

```bash
cd /home/muqiao/dev/ros2
./tools/fishbot_stack.sh slam-reset
./tools/fishbot_stack.sh slam-base
./tools/fishbot_stack.sh preflight-slam
./tools/fishbot_stack.sh slam-core
./tools/fishbot_stack.sh slam-rviz
./tools/fishbot.sh arrows
```

If `preflight-slam` reports missing `/odom`, fix the micro-ROS control chain before moving the robot.

## License

This is a learning and integration snapshot. Verify licenses of upstream FishBot/FishROS components before redistribution in a product.
