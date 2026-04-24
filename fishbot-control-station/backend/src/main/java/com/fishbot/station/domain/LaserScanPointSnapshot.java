package com.fishbot.station.domain;

public record LaserScanPointSnapshot(
        double angleRad,
        double rangeMeters,
        double x,
        double y) {
}
