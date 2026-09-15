package com.fishbot.station.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.domain.LaserScanPointSnapshot;
import com.fishbot.station.domain.LaserScanRuntimeSnapshot;
import com.fishbot.station.domain.PerceptionRuntimeSnapshot;
import com.fishbot.station.domain.ProximitySensorRuntimeSnapshot;

@Service
public class PerceptionStateService {

    private static final Instant NEVER = Instant.EPOCH;
    private static final int MAX_SCAN_POINTS = 72;
    private static final double ULTRASONIC_BLOCKED_METERS = 0.35;
    private static final double INFRARED_BLOCKED_METERS = 0.18;

    private final AtomicReference<LaserScanRuntimeSnapshot> scanState;
    private final AtomicReference<ProximitySensorRuntimeSnapshot> ultrasonicState;
    private final AtomicReference<ProximitySensorRuntimeSnapshot> infraredState;

    public PerceptionStateService(StationRuntimeProperties runtimeProperties) {
        boolean offline = runtimeProperties.isOfflineTelemetry();
        this.scanState = new AtomicReference<>(offline ? offlineScanSnapshot() : waitingScanSnapshot());
        this.ultrasonicState = new AtomicReference<>(offline
                ? offlineRangeSnapshot("/ultrasonic", "ultrasonic_link", 0.42, 2.0, "offline ultrasonic preview")
                : waitingRangeSnapshot("/ultrasonic", "waiting for /ultrasonic"));
        this.infraredState = new AtomicReference<>(offline
                ? offlineRangeSnapshot("/infrared", "infrared_link", 0.24, 0.8, "offline infrared preview")
                : waitingRangeSnapshot("/infrared", "waiting for /infrared"));
    }

    public PerceptionRuntimeSnapshot snapshot() {
        return new PerceptionRuntimeSnapshot(
                scanState.get(),
                ultrasonicState.get(),
                infraredState.get());
    }

    public void updateFromScan(JsonNode msg, Instant timestamp) {
        String frameId = msg.path("header").path("frame_id").asText("laser_link");
        double angleMin = msg.path("angle_min").asDouble(0.0);
        double angleIncrement = msg.path("angle_increment").asDouble(0.0);
        double rangeMin = msg.path("range_min").asDouble(0.0);
        double rangeMax = msg.path("range_max").asDouble(0.0);
        JsonNode ranges = msg.path("ranges");
        int beamCount = ranges.isArray() ? ranges.size() : 0;
        int stride = beamCount > MAX_SCAN_POINTS ? (int) Math.ceil((double) beamCount / MAX_SCAN_POINTS) : 1;
        List<LaserScanPointSnapshot> points = new ArrayList<>();
        double observedRange = 0.0;

        if (ranges.isArray()) {
            for (int i = 0; i < beamCount; i += stride) {
                JsonNode rangeNode = ranges.path(i);
                if (!rangeNode.isNumber()) {
                    continue;
                }
                double range = rangeNode.asDouble();
                if (!Double.isFinite(range) || range <= 0.0) {
                    continue;
                }
                if (rangeMin > 0.0 && range < rangeMin) {
                    continue;
                }
                if (rangeMax > 0.0 && range > rangeMax) {
                    continue;
                }
                double angle = angleMin + (angleIncrement * i);
                points.add(new LaserScanPointSnapshot(
                        angle,
                        range,
                        range * Math.cos(angle),
                        range * Math.sin(angle)));
                observedRange = Math.max(observedRange, range);
            }
        }

        boolean ready = beamCount > 0 && !points.isEmpty();
        double angleMax = beamCount > 0 ? angleMin + (angleIncrement * Math.max(beamCount - 1, 0)) : angleMin;
        scanState.set(new LaserScanRuntimeSnapshot(
                ready,
                frameId,
                beamCount,
                angleMin,
                angleMax,
                rangeMin,
                rangeMax,
                observedRange,
                timestamp,
                ready ? "laser scan sampled" : "scan payload incomplete",
                List.copyOf(points)));
    }

    public void updateUltrasonicRange(JsonNode msg, Instant timestamp, String topic) {
        ultrasonicState.set(buildRangeSnapshot(msg, timestamp, topic, ULTRASONIC_BLOCKED_METERS, "ultrasonic range observed"));
    }

    public void updateInfraredRange(JsonNode msg, Instant timestamp, String topic) {
        infraredState.set(buildRangeSnapshot(msg, timestamp, topic, INFRARED_BLOCKED_METERS, "infrared range observed"));
    }

    private static ProximitySensorRuntimeSnapshot buildRangeSnapshot(
            JsonNode msg,
            Instant timestamp,
            String topic,
            double blockedThreshold,
            String statusMessage) {
        String frameId = msg.path("header").path("frame_id").asText("");
        double distance = msg.path("range").asDouble(Double.NaN);
        double maxRange = msg.path("max_range").asDouble(0.0);
        boolean ready = Double.isFinite(distance);

        return new ProximitySensorRuntimeSnapshot(
                ready,
                topic,
                frameId,
                ready ? distance : 0.0,
                maxRange,
                ready && distance <= blockedThreshold,
                timestamp,
                ready ? statusMessage : "range payload incomplete");
    }

    private static LaserScanRuntimeSnapshot waitingScanSnapshot() {
        return new LaserScanRuntimeSnapshot(
                false,
                "laser_link",
                0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                NEVER,
                "waiting for /scan",
                List.of());
    }

    private static ProximitySensorRuntimeSnapshot waitingRangeSnapshot(String topic, String statusMessage) {
        return new ProximitySensorRuntimeSnapshot(
                false,
                topic,
                "",
                0.0,
                0.0,
                false,
                NEVER,
                statusMessage);
    }

    private static LaserScanRuntimeSnapshot offlineScanSnapshot() {
        List<LaserScanPointSnapshot> points = List.of(
                point(-1.1, 1.2),
                point(-0.6, 1.8),
                point(-0.2, 2.1),
                point(0.2, 1.9),
                point(0.55, 1.3),
                point(0.9, 0.92));

        return new LaserScanRuntimeSnapshot(
                true,
                "laser_link",
                6,
                -1.1,
                0.9,
                0.12,
                8.0,
                2.1,
                Instant.now(),
                "offline scan preview",
                points);
    }

    private static ProximitySensorRuntimeSnapshot offlineRangeSnapshot(
            String topic,
            String frameId,
            double distance,
            double maxRange,
            String statusMessage) {
        return new ProximitySensorRuntimeSnapshot(
                true,
                topic,
                frameId,
                distance,
                maxRange,
                false,
                Instant.now(),
                statusMessage);
    }

    private static LaserScanPointSnapshot point(double angle, double range) {
        return new LaserScanPointSnapshot(
                angle,
                range,
                range * Math.cos(angle),
                range * Math.sin(angle));
    }
}
