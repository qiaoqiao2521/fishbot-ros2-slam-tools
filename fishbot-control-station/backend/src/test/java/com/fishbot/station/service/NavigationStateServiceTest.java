package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fishbot.station.config.StationRuntimeProperties;

class NavigationStateServiceTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void updatesMapSnapshotFromOccupancyGrid() throws Exception {
        NavigationStateService service = new NavigationStateService(new StationRuntimeProperties());
        Instant now = Instant.parse("2026-03-18T03:00:00Z");

        String json = """
                {
                  "info": {
                    "resolution": 0.05,
                    "width": 384,
                    "height": 256,
                    "origin": {
                      "position": { "x": -3.9, "y": -1.82 },
                      "orientation": { "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0 }
                    }
                  },
                  "data": [0, 100, -1, 0, 42, 100]
                }
                """;

        service.updateFromMap(objectMapper.readTree(json), now);

        var snapshot = service.snapshot().map();
        assertTrue(snapshot.ready());
        assertEquals(384, snapshot.width());
        assertEquals(256, snapshot.height());
        assertEquals(0.05, snapshot.resolution(), 1e-6);
        assertEquals(-3.9, snapshot.originX(), 1e-6);
        assertEquals(-1.82, snapshot.originY(), 1e-6);
        assertEquals(0.0, snapshot.originYaw(), 1e-6);
        assertTrue(snapshot.sampleStride() > 1);
        assertFalse(snapshot.sampledCells().isEmpty());
        assertEquals(now, snapshot.lastUpdate());
    }

    @Test
    void updatesTfSnapshotFromTransformMessages() throws Exception {
        NavigationStateService service = new NavigationStateService(new StationRuntimeProperties());
        Instant now = Instant.parse("2026-03-18T03:01:00Z");

        String json = """
                {
                  "transforms": [
                    { "header": { "frame_id": "map" }, "child_frame_id": "odom" },
                    { "header": { "frame_id": "odom" }, "child_frame_id": "base_footprint" }
                  ]
                }
                """;

        service.updateFromTf(objectMapper.readTree(json), now, false);

        var snapshot = service.snapshot().tf();
        assertTrue(snapshot.ready());
        assertTrue(snapshot.mapToOdomPresent());
        assertTrue(snapshot.odomToBasePresent());
        assertEquals(2, snapshot.transformCount());
    }

    @Test
    void updatesLocalizationSnapshotFromAmclPose() throws Exception {
        NavigationStateService service = new NavigationStateService(new StationRuntimeProperties());
        Instant now = Instant.parse("2026-03-18T03:02:00Z");

        String json = """
                {
                  "pose": {
                    "pose": {
                      "position": { "x": 2.4, "y": -1.2 },
                      "orientation": { "x": 0.0, "y": 0.0, "z": 0.3826834, "w": 0.9238795 }
                    },
                    "covariance": [0.04, 0, 0, 0, 0, 0, 0, 0.09, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.16]
                  }
                }
                """;

        service.updateFromLocalization(objectMapper.readTree(json), now);

        var snapshot = service.snapshot().localization();
        assertTrue(snapshot.ready());
        assertEquals(2.4, snapshot.x(), 1e-6);
        assertEquals(-1.2, snapshot.y(), 1e-6);
        assertTrue(Math.abs(snapshot.yaw() - (Math.PI / 4.0)) < 1e-3);
        assertEquals(0.16, snapshot.covarianceScore(), 1e-6);
    }

    @Test
    void updatesNavStatusSnapshotFromGoalStatusArray() throws Exception {
        NavigationStateService service = new NavigationStateService(new StationRuntimeProperties());
        Instant now = Instant.parse("2026-03-18T03:03:00Z");

        String json = """
                {
                  "status_list": [
                    { "status": 2 },
                    { "status": 4 },
                    { "status": 6 }
                  ]
                }
                """;

        service.updateFromNavStatus(objectMapper.readTree(json), now);

        var snapshot = service.snapshot().navStatus();
        assertTrue(snapshot.ready());
        assertEquals(1, snapshot.activeGoals());
        assertEquals(3, snapshot.totalGoals());
        assertTrue(snapshot.statusSummary().contains("EXECUTING"));
    }

    @Test
    void startsWithOfflineShellHintsWhenOfflineModeEnabled() {
        StationRuntimeProperties props = new StationRuntimeProperties();
        props.setTelemetryMode("offline");
        NavigationStateService service = new NavigationStateService(props);

        var snapshot = service.snapshot();
        assertFalse(snapshot.map().ready());
        assertTrue(snapshot.map().statusMessage().contains("offline"));
        assertTrue(snapshot.navStatus().statusMessage().contains("offline"));
    }
}
