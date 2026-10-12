package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.Test;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.ros.RosbridgeClient;

class RosTimeServiceTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final AtomicLong steady = new AtomicLong(10_000_000_000L);
    private RosTimeService clock(boolean simulation, RosbridgeClient client) {
        StationRuntimeProperties properties = new StationRuntimeProperties();
        properties.setUseSimTime(simulation);
        return new RosTimeService(properties, client, steady::get);
    }

    @Test
    void physicalClockUsesEpochTime() {
        long before = Instant.now().getEpochSecond();
        var stamp = clock(false, mock(RosbridgeClient.class)).stamp();
        long after = Instant.now().getEpochSecond();
        long seconds = ((Number) stamp.get("sec")).longValue();
        assertTrue(seconds >= before && seconds <= after);
        assertTrue(((Number) stamp.get("nanosec")).longValue() >= 0);
    }

    @Test
    void absentSimulationClockNeverFallsBackToEpoch() {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.isConnected()).thenReturn(true);
        assertThrows(RosClockUnavailableException.class, () -> clock(true, client).stamp());
    }

    @Test
    void repeatedFrozenClockPacketsCannotKeepClockHealthy() throws Exception {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.isConnected()).thenReturn(true);
        RosTimeService service = clock(true, client);
        var msg = mapper.readTree("{\"clock\":{\"sec\":12,\"nanosec\":123}}");
        service.updateClock(msg);
        assertEquals(12L, service.stamp().get("sec"));
        steady.addAndGet(1_100_000_000L);
        service.updateClock(msg);
        assertThrows(RosClockUnavailableException.class, service::stamp);
        service.updateClock(mapper.readTree("{\"clock\":{\"sec\":12,\"nanosec\":124}}"));
        assertEquals(124L, service.stamp().get("nanosec"));
    }

    @Test
    void staleOrDisconnectedClockIsRejected() throws Exception {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.isConnected()).thenReturn(true);
        RosTimeService service = clock(true, client);
        service.updateClock(mapper.readTree("{\"clock\":{\"sec\":12,\"nanosec\":0}}"));
        when(client.isConnected()).thenReturn(false);
        assertThrows(RosClockUnavailableException.class, service::stamp);
        when(client.isConnected()).thenReturn(true);
        when(client.getConnectionGeneration()).thenReturn(1L);
        assertThrows(RosClockUnavailableException.class, service::stamp);
        when(client.getConnectionGeneration()).thenReturn(0L);
        steady.addAndGet(1_100_000_000L);
        assertThrows(RosClockUnavailableException.class, service::stamp);
    }

    @Test
    void malformedClockClearsPriorClock() throws Exception {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.isConnected()).thenReturn(true);
        RosTimeService service = clock(true, client);
        service.updateClock(mapper.readTree("{\"clock\":{\"sec\":12,\"nanosec\":0}}"));
        service.updateClock(mapper.readTree("{\"clock\":{\"sec\":12,\"nanosec\":1000000000}}"));
        assertThrows(RosClockUnavailableException.class, service::stamp);
    }
}
