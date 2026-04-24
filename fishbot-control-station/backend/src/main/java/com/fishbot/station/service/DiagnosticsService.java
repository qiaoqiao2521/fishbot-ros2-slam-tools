package com.fishbot.station.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.LinkedList;
import java.util.List;

import org.springframework.stereotype.Service;

import com.fishbot.station.domain.DiagnosticEntry;
import com.fishbot.station.domain.DiagnosticSnapshot;

@Service
public class DiagnosticsService {

    private static final int MAX_ENTRIES = 50;
    private final Deque<DiagnosticEntry> ring = new LinkedList<>();

    public void recordCommand(String source, String message) {
        addEntry(new DiagnosticEntry(Instant.now(), source, message, "INFO"));
    }

    public void recordError(String source, String message) {
        addEntry(new DiagnosticEntry(Instant.now(), source, message, "ERROR"));
    }

    private synchronized void addEntry(DiagnosticEntry entry) {
        if (ring.size() >= MAX_ENTRIES) {
            ring.removeFirst();
        }
        ring.addLast(entry);
    }

    public DiagnosticSnapshot latestSnapshot() {
        List<DiagnosticEntry> copy = new ArrayList<>(ring);
        Collections.reverse(copy);
        return new DiagnosticSnapshot(Instant.now(), copy);
    }
}
