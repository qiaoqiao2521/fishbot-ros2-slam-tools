package com.fishbot.station.service;

import java.time.Instant;
import java.util.Locale;
import java.util.Map;
import java.util.StringJoiner;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.ros.RosbridgeClient;

import reactor.core.publisher.Mono;

@Service
public class RosTopicService {
    private final Object commandGate = new Object();
    private boolean stopLatched;

    private final RosbridgeClient client;
    private final DiagnosticsService diagnosticsService;
    private final StationRuntimeProperties runtimeProperties;
    private final NavigationStateService navigationStateService;
    private final RosTimeService rosTimeService;

    public RosTopicService(@Qualifier("controlRosbridgeClient") RosbridgeClient client,
                           DiagnosticsService diagnosticsService,
                           StationRuntimeProperties runtimeProperties,
                           NavigationStateService navigationStateService,
                           RosTimeService rosTimeService) {
        this.client = client;
        this.diagnosticsService = diagnosticsService;
        this.runtimeProperties = runtimeProperties;
        this.navigationStateService = navigationStateService;
        this.rosTimeService = rosTimeService;
    }

    public Mono<Void> publishCmdVel(double linearX, double angularZ, String source, long sequence) {
        String payload = buildTwistPayload(linearX, angularZ);
        diagnosticsService.recordCommand(source, "cmd_vel:" + payload + " seq:" + sequence);
        if (runtimeProperties.isOfflineTelemetry()) {
            return Mono.empty();
        }
        return advertise().then(Mono.defer(() -> {
            synchronized (commandGate) {
                if (stopLatched) return Mono.error(new StationStopLatchedException());
                return client.send(payload);
            }
        }));
    }

    public Mono<Void> publishGoalPose(double x, double y, double yaw, String source) {
        validatePose(x, y, yaw);
        return Mono.defer(() -> {
            synchronized (commandGate) {
                if (stopLatched) return Mono.error(new StationStopLatchedException());
                navigationStateService.invalidatePath("new goal submitted; waiting for a new /plan", Instant.now());
                if (runtimeProperties.isOfflineTelemetry()) {
                    diagnosticsService.recordCommand(source, "offline goal preview; no Nav2 dispatch: " + x + "," + y + "," + yaw);
                    return Mono.empty();
                }
            }
            return client.send("{\"op\":\"advertise\",\"topic\":\"/goal_pose\",\"type\":\"geometry_msgs/PoseStamped\"}")
                .then(Mono.defer(() -> {
                    synchronized (commandGate) {
                        if (stopLatched) return Mono.error(new StationStopLatchedException());
                        String payload = buildPoseStampedPayload(x, y, yaw);
                        diagnosticsService.recordCommand(source, "goal_pose:" + payload);
                        return client.send(payload);
                    }
                }));
        });
    }

    public Mono<Void> publishInitialPose(double x, double y, double yaw, String source) {
        validatePose(x, y, yaw);
        return Mono.defer(() -> {
            synchronized (commandGate) {
                if (stopLatched) return Mono.error(new StationStopLatchedException());
                navigationStateService.invalidatePath("initial pose submitted; waiting for a new /plan", Instant.now());
                if (runtimeProperties.isOfflineTelemetry()) {
                    navigationStateService.applyOfflineInitialPose(x, y, yaw, Instant.now());
                    diagnosticsService.recordCommand(source, "offline initial pose preview; no AMCL dispatch: " + x + "," + y + "," + yaw);
                    return Mono.empty();
                }
            }
            return client.send("{\"op\":\"advertise\",\"topic\":\"/initialpose\",\"type\":\"geometry_msgs/msg/PoseWithCovarianceStamped\"}")
                    .then(Mono.defer(() -> {
                        synchronized (commandGate) {
                            if (stopLatched) return Mono.error(new StationStopLatchedException());
                            String payload = buildInitialPosePayload(x, y, yaw);
                            diagnosticsService.recordCommand(source, "initialpose:" + payload);
                            return client.send(payload);
                        }
                    }));
        });
    }

    public Mono<Void> publishStop(String reason) {
        diagnosticsService.recordCommand("control", "stop -" + reason + " @ " + Instant.now());
        if (runtimeProperties.isOfflineTelemetry()) {
            return Mono.empty();
        }
        return advertise().then(Mono.defer(() -> client.send(buildTwistPayload(0, 0))));
    }

    public Mono<Void> publishEmergencyStop(String reason) {
        synchronized (commandGate) {
            stopLatched = true;
        }
        diagnosticsService.recordError("emergency-stop", reason);
        return publishStop("emergency");
    }

    private String buildTwistPayload(double linearX, double angularZ) {
        if (!Double.isFinite(linearX) || !Double.isFinite(angularZ)) throw new IllegalArgumentException("Velocity must be finite");
        return String.format(Locale.ROOT, "{\"op\":\"publish\",\"topic\":\"/cmd_vel\",\"msg\":{\"linear\":{\"x\":%.3f,\"y\":0,\"z\":0},\"angular\":{\"x\":0,\"y\":0,\"z\":%.3f}}}",
                linearX, angularZ);
    }

    private String buildPoseStampedPayload(double x, double y, double yaw) {
        return String.format(Locale.ROOT, "{\"op\":\"publish\",\"topic\":\"/goal_pose\",\"msg\":{%s,\"pose\":%s}}",
                headerPayload(), posePayload(x, y, yaw));
    }

    private String buildInitialPosePayload(double x, double y, double yaw) {
        StringJoiner covariance = new StringJoiner(",", "[", "]");
        for (int index = 0; index < 36; index++) {
            covariance.add(index == 0 || index == 7 ? "0.25"
                    : index == 35 ? Double.toString(Math.pow(Math.PI / 12, 2)) : "0");
        }
        return String.format(Locale.ROOT, "{\"op\":\"publish\",\"topic\":\"/initialpose\",\"msg\":{%s,\"pose\":{\"pose\":%s,\"covariance\":%s}}}",
                headerPayload(), posePayload(x, y, yaw), covariance);
    }

    private String headerPayload() {
        Map<String, Object> stamp = rosTimeService.stamp();
        return String.format(Locale.ROOT, "\"header\":{\"frame_id\":\"map\",\"stamp\":{\"sec\":%d,\"nanosec\":%d}}",
                stamp.get("sec"), stamp.get("nanosec"));
    }

    private static String posePayload(double x, double y, double yaw) {
        return String.format(Locale.ROOT, "{\"position\":{\"x\":%.3f,\"y\":%.3f,\"z\":0},\"orientation\":{\"x\":0,\"y\":0,\"z\":%.4f,\"w\":%.4f}}",
                x, y, Math.sin(yaw / 2.0), Math.cos(yaw / 2.0));
    }

    private static void validatePose(double x, double y, double yaw) {
        if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(yaw)) {
            throw new IllegalArgumentException("Pose must be finite");
        }
    }

    private Mono<Void> advertise() {
        return client.send("{\"op\":\"advertise\",\"topic\":\"/cmd_vel\",\"type\":\"geometry_msgs/Twist\"}");
    }
}
