package com.fishbot.station.domain;

import java.time.Instant;
import java.util.List;

public class DiagnosticSnapshot {

    private final Instant generatedAt;
    private final List<DiagnosticEntry> entries;

    public DiagnosticSnapshot(Instant generatedAt, List<DiagnosticEntry> entries) {
        this.generatedAt = generatedAt;
        this.entries = entries;
    }

    public Instant getGeneratedAt() {
        return generatedAt;
    }

    public List<DiagnosticEntry> getEntries() {
        return entries;
    }
}
