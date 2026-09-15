package com.fishbot.station.domain;

import java.time.Instant;

public record BridgeConnectionSnapshot(
        boolean connected,
        boolean telemetryOnline,
        String endpoint,
        Instant lastMessage,
        String statusMessage) {
}
