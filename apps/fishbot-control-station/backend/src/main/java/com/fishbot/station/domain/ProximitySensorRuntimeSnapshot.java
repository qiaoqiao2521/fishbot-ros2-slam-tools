package com.fishbot.station.domain;

import java.time.Instant;

public record ProximitySensorRuntimeSnapshot(
        boolean ready,
        String sourceTopic,
        String frameId,
        double distanceMeters,
        double maxRangeMeters,
        boolean blocked,
        Instant lastUpdate,
        String statusMessage) {
}
