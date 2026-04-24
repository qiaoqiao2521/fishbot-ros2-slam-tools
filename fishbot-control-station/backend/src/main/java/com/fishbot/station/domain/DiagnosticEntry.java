package com.fishbot.station.domain;

import java.time.Instant;

public class DiagnosticEntry {

    private final Instant timestamp;
    private final String source;
    private final String message;
    private final String severity;

    public DiagnosticEntry(Instant timestamp, String source, String message, String severity) {
        this.timestamp = timestamp;
        this.source = source;
        this.message = message;
        this.severity = severity;
    }

    public Instant getTimestamp() {
        return timestamp;
    }

    public String getSource() {
        return source;
    }

    public String getMessage() {
        return message;
    }

    public String getSeverity() {
        return severity;
    }
}
