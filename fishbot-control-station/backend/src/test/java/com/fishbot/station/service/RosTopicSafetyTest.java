package com.fishbot.station.service;

import static org.mockito.Mockito.*;
import org.junit.jupiter.api.Test;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.ros.RosbridgeClient;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class RosTopicSafetyTest {
    @Test
    void queuedVelocityIsRejectedAfterLatch() {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.send(anyString())).thenReturn(Mono.empty());
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), new StationRuntimeProperties());
        Mono<Void> queued = service.publishCmdVel(0.2, 0, "test", 1);
        service.publishEmergencyStop("test").block();
        StepVerifier.create(queued).expectError(IllegalStateException.class).verify();
        verify(client, never()).send(contains("0.200"));
        verify(client).send(contains("\"op\":\"publish\""));
    }
}
