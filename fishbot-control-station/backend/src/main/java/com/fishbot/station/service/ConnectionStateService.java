package com.fishbot.station.service;

import java.time.Instant;
import java.time.Duration;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import com.fishbot.station.config.RosbridgeChannelsProperties;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.domain.BridgeConnectionSnapshot;
import com.fishbot.station.domain.ConnectionSnapshot;
import com.fishbot.station.ros.RosbridgeClient;

@Service
public class ConnectionStateService {

    private final RosbridgeClient controlRosbridgeClient;
    private final RosbridgeClient laserRosbridgeClient;
    private final RosbridgeChannelsProperties rosbridgeChannelsProperties;
    private final StationRuntimeProperties runtimeProperties;
    private final RobotStateService robotStateService;
    private final NavigationStateService navigationStateService;
    private final PerceptionStateService perceptionStateService;
    private final DiagnosticsService diagnosticsService;
    private final EventStreamService eventStreamService;

    public ConnectionStateService(@Qualifier("controlRosbridgeClient") RosbridgeClient controlRosbridgeClient,
                                  @Qualifier("laserRosbridgeClient") RosbridgeClient laserRosbridgeClient,
                                  RosbridgeChannelsProperties rosbridgeChannelsProperties,
                                  StationRuntimeProperties runtimeProperties,
                                  RobotStateService robotStateService,
                                  NavigationStateService navigationStateService,
                                  PerceptionStateService perceptionStateService,
                                  DiagnosticsService diagnosticsService,
                                  EventStreamService eventStreamService) {
        this.controlRosbridgeClient = controlRosbridgeClient;
        this.laserRosbridgeClient = laserRosbridgeClient;
        this.rosbridgeChannelsProperties = rosbridgeChannelsProperties;
        this.runtimeProperties = runtimeProperties;
        this.robotStateService = robotStateService;
        this.navigationStateService = navigationStateService;
        this.perceptionStateService = perceptionStateService;
        this.diagnosticsService = diagnosticsService;
        this.eventStreamService = eventStreamService;
    }

    public ConnectionSnapshot snapshot() {
        if (runtimeProperties.isOfflineTelemetry()) {
            Instant timestamp = robotStateService.getCurrentState().getTimestamp();
            BridgeConnectionSnapshot controlBridge = new BridgeConnectionSnapshot(
                    true,
                    true,
                    "offline://control-simulator",
                    Instant.EPOCH.equals(timestamp) ? Instant.now() : timestamp,
                    "offline-sim");
            BridgeConnectionSnapshot laserBridge = new BridgeConnectionSnapshot(
                    true,
                    true,
                    "offline://laser-simulator",
                    Instant.now(),
                    "offline-sim");
            return new ConnectionSnapshot(
                    true,
                    true,
                    controlBridge.endpoint(),
                    controlBridge.lastMessage(),
                    "offline-sim",
                    controlBridge,
                    laserBridge);
        }

        BridgeConnectionSnapshot controlBridge = snapshotFor(
                controlRosbridgeClient,
                rosbridgeChannelsProperties.getControl().getUrl());
        BridgeConnectionSnapshot laserBridge = snapshotFor(
                laserRosbridgeClient,
                rosbridgeChannelsProperties.getLaser().getUrl());
        return new ConnectionSnapshot(
                controlBridge.connected(),
                controlBridge.telemetryOnline(),
                controlBridge.endpoint(),
                controlBridge.lastMessage(),
                controlBridge.statusMessage(),
                controlBridge,
                laserBridge);
    }

    private BridgeConnectionSnapshot snapshotFor(RosbridgeClient client, String endpoint) {
        boolean connected = client.isConnected();
        Instant lastMessage = client.getLastMessageTime();
        boolean telemetryOnline = connected
                && !Instant.EPOCH.equals(lastMessage)
                && Duration.between(lastMessage, Instant.now()).toSeconds() < 3;
        String statusMessage = connected ? (telemetryOnline ? "connected" : "connected-no-telemetry") : "disconnected";
        return new BridgeConnectionSnapshot(connected, telemetryOnline, endpoint, lastMessage, statusMessage);
    }

    @Scheduled(fixedDelayString = "2500")
    public void publishCurrentState() {
        eventStreamService.publishConnection(snapshot());
        eventStreamService.publishRobotState(robotStateService.getCurrentState());
        eventStreamService.publishNavigationState(navigationStateService.snapshot());
        eventStreamService.publishPerceptionState(perceptionStateService.snapshot());
        eventStreamService.publishDiagnostic(diagnosticsService.latestSnapshot());
    }
}
