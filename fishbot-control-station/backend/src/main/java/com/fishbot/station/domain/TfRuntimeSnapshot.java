package com.fishbot.station.domain;

import java.time.Instant;

public record TfRuntimeSnapshot(
        boolean ready,
        boolean mapToOdomPresent,
        boolean odomToBasePresent,
        int transformCount,
        int staticTransformCount,
        Instant lastUpdate,
        String statusMessage) {
}
