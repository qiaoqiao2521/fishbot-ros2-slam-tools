package com.fishbot.station.domain;

import java.time.Instant;

public class EventMessage<T> {

    private final EventType type;
    private final T payload;
    private final Instant timestamp;

    public EventMessage(EventType type, T payload, Instant timestamp) {
        this.type = type;
        this.payload = payload;
        this.timestamp = timestamp;
    }

    public EventType getType() {
        return type;
    }

    public T getPayload() {
        return payload;
    }

    public Instant getTimestamp() {
        return timestamp;
    }
}
