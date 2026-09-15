package com.fishbot.station.domain;

import java.time.Instant;
import java.util.List;

public record MapRuntimeSnapshot(
        boolean ready,
        int width,
        int height,
        double resolution,
        double originX,
        double originY,
        double originYaw,
        int sampleStride,
        Instant lastUpdate,
        String statusMessage,
        List<MapCellSnapshot> sampledCells) {
}
