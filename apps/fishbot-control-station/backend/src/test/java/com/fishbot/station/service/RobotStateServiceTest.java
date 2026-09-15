package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

class RobotStateServiceTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void updatesFromOdomMessage() throws Exception {
        RobotStateService service = new RobotStateService();
        Instant now = Instant.parse("2026-03-17T15:00:00Z");

        String json = """
                {
                  "pose": { "pose": { "position": { "x": 1.25, "y": -0.5 }, "orientation": { "x": 0.0, "y": 0.0, "z": 0.7071068, "w": 0.7071068 } } },
                  "twist": { "twist": { "linear": { "x": 0.12 }, "angular": { "z": 0.34 } } }
                }
                """;

        service.updateFromOdom(objectMapper.readTree(json), now);

        var state = service.getCurrentState();
        assertEquals(1.25, state.getX(), 1e-6);
        assertEquals(-0.5, state.getY(), 1e-6);
        assertEquals(0.12, state.getLinearVelocity(), 1e-6);
        assertEquals(0.34, state.getAngularVelocity(), 1e-6);
        assertTrue(Math.abs(state.getYaw() - (Math.PI / 2.0)) < 1e-3);
        assertEquals(now, state.getTimestamp());
    }

    @Test
    void updatesFromImuMessage() throws Exception {
        RobotStateService service = new RobotStateService();
        Instant now = Instant.parse("2026-03-17T15:01:00Z");

        service.updateFromOdom(objectMapper.readTree("""
                {
                  "pose": { "pose": { "position": { "x": 0.0, "y": 0.0 }, "orientation": { "x": 0.0, "y": 0.0, "z": 0.5769585, "w": 0.8167734 } } },
                  "twist": { "twist": { "linear": { "x": 0.0 }, "angular": { "z": 0.0 } } }
                }
                """), now.minusSeconds(1));

        String json = """
                {
                  "orientation": { "x": 0.0, "y": 0.0, "z": 0.3826834, "w": 0.9238795 },
                  "angular_velocity": { "x": 0.01, "y": 0.02, "z": 0.03 },
                  "linear_acceleration": { "x": 0.11, "y": 0.22, "z": 9.81 }
                }
                """;

        service.updateFromImu(objectMapper.readTree(json), now);

        var state = service.getCurrentState();
        assertEquals(0.11, state.getAccelX(), 1e-6);
        assertEquals(0.22, state.getAccelY(), 1e-6);
        assertEquals(9.81, state.getAccelZ(), 1e-6);
        assertEquals(0.01, state.getAngularVelX(), 1e-6);
        assertEquals(0.02, state.getAngularVelY(), 1e-6);
        assertEquals(0.03, state.getAngularVelZ(), 1e-6);
        assertTrue(Math.abs(state.getYaw() - 1.23) < 1e-3);
        assertEquals(now, state.getTimestamp());
    }
}
