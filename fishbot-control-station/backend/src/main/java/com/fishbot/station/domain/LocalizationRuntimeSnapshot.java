package com.fishbot.station.domain;

import java.time.Instant;

public record LocalizationRuntimeSnapshot(
        boolean ready,
        double x,
        double y,
        double yaw,
        double covarianceScore,
        Instant lastUpdate,
        String statusMessage) {
}
