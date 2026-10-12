package com.fishbot.station.service;

import java.time.Instant;
import java.util.Map;
import java.util.function.LongSupplier;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.ros.RosbridgeClient;

@Service
public class RosTimeService {
    private final StationRuntimeProperties properties;
    private final RosbridgeClient client;
    private final LongSupplier steadyNow;
    private Long clockNs;
    private long lastReceipt, lastAdvance;
    private long clockConnectionGeneration;
    private static final long MAX_CLOCK_AGE_NS = 1_000_000_000L;

    @Autowired
    public RosTimeService(StationRuntimeProperties properties,
            @Qualifier("controlRosbridgeClient") RosbridgeClient client) {
        this(properties, client, System::nanoTime);
    }

    RosTimeService(StationRuntimeProperties properties, RosbridgeClient client, LongSupplier steadyNow) {
        this.properties = properties;
        this.client = client;
        this.steadyNow = steadyNow;
    }

    public synchronized void updateClock(JsonNode msg) {
        JsonNode seconds = msg.path("clock").path("sec");
        JsonNode nanoseconds = msg.path("clock").path("nanosec");
        if (!seconds.isIntegralNumber() || !seconds.canConvertToInt() || seconds.asLong() < 0
                || !nanoseconds.isIntegralNumber() || !nanoseconds.canConvertToInt()
                || nanoseconds.asInt() < 0 || nanoseconds.asInt() >= 1_000_000_000) {
            clockNs = null;
            return;
        }
        long next = seconds.asLong() * 1_000_000_000L + nanoseconds.asLong();
        long now = steadyNow.getAsLong();
        if (clockNs == null || next != clockNs) lastAdvance = now;
        clockNs = next;
        lastReceipt = now;
        clockConnectionGeneration = client.getConnectionGeneration();
    }

    public synchronized Map<String, Object> stamp() {
        if (!properties.isUseSimTime()) {
            Instant now = Instant.now();
            return Map.of("sec", now.getEpochSecond(), "nanosec", now.getNano());
        }
        long now = steadyNow.getAsLong();
        if (!client.isConnected() || clockNs == null || clockConnectionGeneration != client.getConnectionGeneration()
                || now - lastReceipt > MAX_CLOCK_AGE_NS
                || now - lastAdvance > MAX_CLOCK_AGE_NS) {
            throw new RosClockUnavailableException();
        }
        // Use the observed ROS clock directly. Never extrapolate it with wall time.
        return Map.of("sec", clockNs / 1_000_000_000L, "nanosec", clockNs % 1_000_000_000L);
    }
}
