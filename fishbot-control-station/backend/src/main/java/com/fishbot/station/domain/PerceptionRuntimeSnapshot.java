package com.fishbot.station.domain;

public record PerceptionRuntimeSnapshot(
        LaserScanRuntimeSnapshot scan,
        ProximitySensorRuntimeSnapshot ultrasonic,
        ProximitySensorRuntimeSnapshot infrared) {
}
