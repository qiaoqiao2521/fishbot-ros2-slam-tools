package com.fishbot.station.domain;

import java.time.Instant;

public record NavStatusRuntimeSnapshot(
        boolean ready,
        int activeGoals,
        int totalGoals,
        String statusSummary,
        Instant lastUpdate,
        String statusMessage) {
}
