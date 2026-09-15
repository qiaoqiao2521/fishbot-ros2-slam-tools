package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fishbot.station.config.StationRuntimeProperties;

class PerceptionStateServiceTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void updatesScanSnapshotFromLaserScan() throws Exception {
        PerceptionStateService service = new PerceptionStateService(new StationRuntimeProperties());
        Instant now = Instant.parse("2026-03-18T04:00:00Z");

        String json = """
                {
                  "header": { "frame_id": "laser_link" },
                  "angle_min": -1.5708,
                  "angle_increment": 0.7854,
                  "range_min": 0.12,
                  "range_max": 8.0,
                  "ranges": [0.5, 1.2, 2.4, 0.0, 9.5, 1.8]
                }
                """;

        service.updateFromScan(objectMapper.readTree(json), now);

        var snapshot = service.snapshot().scan();
        assertTrue(snapshot.ready());
        assertEquals("laser_link", snapshot.frameId());
        assertEquals(6, snapshot.beamCount());
        assertEquals(4, snapshot.samplePoints().size());
        assertTrue(snapshot.observedRange() > 2.3);
        assertEquals(now, snapshot.lastUpdate());
    }

    @Test
    void updatesUltrasonicAndInfraredFromRangeMessages() throws Exception {
        PerceptionStateService service = new PerceptionStateService(new StationRuntimeProperties());
        Instant now = Instant.parse("2026-03-18T04:01:00Z");

        String ultrasonic = """
                {
                  "header": { "frame_id": "ultrasonic_link" },
                  "range": 0.28,
                  "min_range": 0.02,
                  "max_range": 2.0
                }
                """;

        String infrared = """
                {
                  "header": { "frame_id": "infrared_link" },
                  "range": 0.14,
                  "min_range": 0.02,
                  "max_range": 0.8
                }
                """;

        service.updateUltrasonicRange(objectMapper.readTree(ultrasonic), now, "/ultrasonic");
        service.updateInfraredRange(objectMapper.readTree(infrared), now, "/infrared");

        var snapshot = service.snapshot();
        assertTrue(snapshot.ultrasonic().ready());
        assertEquals("/ultrasonic", snapshot.ultrasonic().sourceTopic());
        assertEquals(0.28, snapshot.ultrasonic().distanceMeters(), 1e-6);
        assertTrue(snapshot.ultrasonic().blocked());

        assertTrue(snapshot.infrared().ready());
        assertEquals("/infrared", snapshot.infrared().sourceTopic());
        assertEquals(0.14, snapshot.infrared().distanceMeters(), 1e-6);
        assertTrue(snapshot.infrared().blocked());
    }

    @Test
    void startsWithOfflineHintsWhenOfflineTelemetryEnabled() {
        StationRuntimeProperties props = new StationRuntimeProperties();
        props.setTelemetryMode("offline");

        PerceptionStateService service = new PerceptionStateService(props);

        var snapshot = service.snapshot();
        assertFalse(snapshot.scan().samplePoints().isEmpty());
        assertTrue(snapshot.scan().statusMessage().contains("offline"));
        assertTrue(snapshot.ultrasonic().statusMessage().contains("offline"));
        assertTrue(snapshot.infrared().statusMessage().contains("offline"));
    }
}
