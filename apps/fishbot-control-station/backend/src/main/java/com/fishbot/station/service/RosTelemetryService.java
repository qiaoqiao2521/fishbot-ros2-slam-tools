package com.fishbot.station.service;

import java.time.Instant;

import jakarta.annotation.PostConstruct;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fishbot.station.ros.RosbridgeClient;

@Service
public class RosTelemetryService {

    private final RosbridgeClient controlRosbridgeClient;
    private final RosbridgeClient laserRosbridgeClient;
    private final RobotStateService robotStateService;
    private final NavigationStateService navigationStateService;
    private final PerceptionStateService perceptionStateService;
    private final DiagnosticsService diagnosticsService;
    private final ObjectMapper objectMapper;

    public RosTelemetryService(@Qualifier("controlRosbridgeClient") RosbridgeClient controlRosbridgeClient,
                               @Qualifier("laserRosbridgeClient") RosbridgeClient laserRosbridgeClient,
                               RobotStateService robotStateService,
                               NavigationStateService navigationStateService,
                               PerceptionStateService perceptionStateService,
                               DiagnosticsService diagnosticsService,
                               ObjectMapper objectMapper) {
        this.controlRosbridgeClient = controlRosbridgeClient;
        this.laserRosbridgeClient = laserRosbridgeClient;
        this.robotStateService = robotStateService;
        this.navigationStateService = navigationStateService;
        this.perceptionStateService = perceptionStateService;
        this.diagnosticsService = diagnosticsService;
        this.objectMapper = objectMapper;
    }

    @PostConstruct
    public void subscribe() {
        controlRosbridgeClient.incomingMessages().subscribe(this::handleControlMessage, error ->
                diagnosticsService.recordError("rosbridge-control", "incoming stream error: " + error.getMessage()));
        laserRosbridgeClient.incomingMessages().subscribe(this::handleLaserMessage, error ->
                diagnosticsService.recordError("rosbridge-laser", "incoming stream error: " + error.getMessage()));
    }

    private void handleControlMessage(String payload) {
        handleMessage(payload, true);
    }

    private void handleLaserMessage(String payload) {
        handleMessage(payload, false);
    }

    private void handleMessage(String payload, boolean controlBridge) {
        try {
            JsonNode root = objectMapper.readTree(payload);
            if (!"publish".equals(root.path("op").asText())) {
                return;
            }

            String topic = root.path("topic").asText("");
            JsonNode msg = root.path("msg");
            Instant now = Instant.now();

            switch (topic) {
                case "/odom" -> {
                    if (controlBridge) {
                        robotStateService.updateFromOdom(msg, now);
                    }
                }
                case "/imu" -> {
                    if (controlBridge) {
                        robotStateService.updateFromImu(msg, now);
                    }
                }
                case "/scan" -> {
                    if (!controlBridge) {
                        perceptionStateService.updateFromScan(msg, now);
                    }
                }
                case "/map" -> {
                    if (!controlBridge) {
                        navigationStateService.updateFromMap(msg, now);
                    }
                }
                case "/tf" -> {
                    if (!controlBridge) {
                        navigationStateService.updateFromTf(msg, now, false);
                    }
                }
                case "/tf_static" -> {
                    if (!controlBridge) {
                        navigationStateService.updateFromTf(msg, now, true);
                    }
                }
                case "/amcl_pose" -> {
                    if (!controlBridge) {
                        navigationStateService.updateFromLocalization(msg, now);
                    }
                }
                case "/navigate_to_pose/_action/status" -> {
                    if (!controlBridge) {
                        navigationStateService.updateFromNavStatus(msg, now);
                    }
                }
                case "/ultrasonic", "/ultrasound" -> {
                    if (!controlBridge) {
                        perceptionStateService.updateUltrasonicRange(msg, now, topic);
                    }
                }
                case "/infrared", "/ir_range" -> {
                    if (!controlBridge) {
                        perceptionStateService.updateInfraredRange(msg, now, topic);
                    }
                }
                default -> {
                    return;
                }
            }
        } catch (Exception ex) {
            diagnosticsService.recordError(controlBridge ? "rosbridge-control" : "rosbridge-laser",
                    "message parse failure: " + ex.getMessage());
        }
    }
}
