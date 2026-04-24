package com.fishbot.station.config;

import java.util.List;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fishbot.station.ros.RosTopicSubscription;
import com.fishbot.station.ros.RosbridgeClient;

@Configuration
public class RosbridgeConfiguration {

    @Bean("controlRosbridgeClient")
    public RosbridgeClient controlRosbridgeClient(
            RosbridgeChannelsProperties rosbridgeChannelsProperties,
            StationRuntimeProperties runtimeProperties,
            ObjectMapper objectMapper) {
        return new RosbridgeClient(
                "control",
                rosbridgeChannelsProperties.getControl(),
                runtimeProperties,
                objectMapper,
                List.of(
                        new RosTopicSubscription("/odom", "nav_msgs/msg/Odometry"),
                        new RosTopicSubscription("/imu", "sensor_msgs/msg/Imu")));
    }

    @Bean("laserRosbridgeClient")
    public RosbridgeClient laserRosbridgeClient(
            RosbridgeChannelsProperties rosbridgeChannelsProperties,
            StationRuntimeProperties runtimeProperties,
            ObjectMapper objectMapper) {
        return new RosbridgeClient(
                "laser",
                rosbridgeChannelsProperties.getLaser(),
                runtimeProperties,
                objectMapper,
                List.of(
                        new RosTopicSubscription("/scan", "sensor_msgs/msg/LaserScan"),
                        new RosTopicSubscription("/map", "nav_msgs/msg/OccupancyGrid"),
                        new RosTopicSubscription("/tf", "tf2_msgs/msg/TFMessage"),
                        new RosTopicSubscription("/tf_static", "tf2_msgs/msg/TFMessage"),
                        new RosTopicSubscription("/amcl_pose", "geometry_msgs/msg/PoseWithCovarianceStamped"),
                        new RosTopicSubscription("/navigate_to_pose/_action/status", "action_msgs/msg/GoalStatusArray"),
                        new RosTopicSubscription("/ultrasonic", "sensor_msgs/msg/Range"),
                        new RosTopicSubscription("/ultrasound", "sensor_msgs/msg/Range"),
                        new RosTopicSubscription("/infrared", "sensor_msgs/msg/Range"),
                        new RosTopicSubscription("/ir_range", "sensor_msgs/msg/Range")));
    }
}
