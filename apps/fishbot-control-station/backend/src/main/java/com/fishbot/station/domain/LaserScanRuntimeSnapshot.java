package com.fishbot.station.domain;

import java.time.Instant;
import java.util.List;

public record LaserScanRuntimeSnapshot(
        boolean ready,
        String frameId,
        int beamCount,
        double angleMin,
        double angleMax,
        double rangeMin,
        double rangeMax,
        double observedRange,
        Instant lastUpdate,
        String statusMessage,
        List<LaserScanPointSnapshot> samplePoints) {
}
