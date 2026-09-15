

网络模式驱动雷达：

```
ros2 run ydlidar ydlidar_node --ros-args -p protocol:=net -p socket_port:=8889
```

串口模式驱动雷达
```
ros2 run ydlidar ydlidar_node --ros-args -p protocol:=serial -p port:=/dev/ttyUSB0
```