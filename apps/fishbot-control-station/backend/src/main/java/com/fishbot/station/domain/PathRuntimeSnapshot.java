package com.fishbot.station.domain;

import java.time.Instant;
import java.util.List;

public record PathRuntimeSnapshot(boolean ready, String frameId, int poseCount,
        List<Point> points, Instant lastUpdate, String statusMessage) {
    public record Point(double x, double y) { }
}
