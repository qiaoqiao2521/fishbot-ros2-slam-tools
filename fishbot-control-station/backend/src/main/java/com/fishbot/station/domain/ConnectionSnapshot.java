package com.fishbot.station.domain;

import java.time.Instant;

public class ConnectionSnapshot {

    private final boolean rosbridgeConnected;
    private final boolean robotOnline;
    private final String rosbridgeUrl;
    private final Instant lastMessage;
    private final String statusMessage;
    private final BridgeConnectionSnapshot controlBridge;
    private final BridgeConnectionSnapshot laserBridge;

    public ConnectionSnapshot(boolean rosbridgeConnected,
                              boolean robotOnline,
                              String rosbridgeUrl,
                              Instant lastMessage,
                              String statusMessage,
                              BridgeConnectionSnapshot controlBridge,
                              BridgeConnectionSnapshot laserBridge) {
        this.rosbridgeConnected = rosbridgeConnected;
        this.robotOnline = robotOnline;
        this.rosbridgeUrl = rosbridgeUrl;
        this.lastMessage = lastMessage;
        this.statusMessage = statusMessage;
        this.controlBridge = controlBridge;
        this.laserBridge = laserBridge;
    }

    public boolean isRosbridgeConnected() {
        return rosbridgeConnected;
    }

    public boolean isRobotOnline() {
        return robotOnline;
    }

    public String getRosbridgeUrl() {
        return rosbridgeUrl;
    }

    public Instant getLastMessage() {
        return lastMessage;
    }

    public String getStatusMessage() {
        return statusMessage;
    }

    public BridgeConnectionSnapshot getControlBridge() {
        return controlBridge;
    }

    public BridgeConnectionSnapshot getLaserBridge() {
        return laserBridge;
    }
}
