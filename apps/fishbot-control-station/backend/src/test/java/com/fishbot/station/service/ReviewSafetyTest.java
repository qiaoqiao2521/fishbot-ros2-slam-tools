package com.fishbot.station.service;

import static org.mockito.Mockito.*;
import org.junit.jupiter.api.Test;
import com.fishbot.station.config.SafetyProperties;
import com.fishbot.station.domain.ControlCommandRequest;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class ReviewSafetyTest {
    @Test
    void nonFiniteVelocityNeverReachesPublisher() {
        RosTopicService topics = mock(RosTopicService.class);
        ControlService service = new ControlService(new SafetyProperties(), topics,
            mock(DiagnosticsService.class), mock(OfflineTelemetryService.class));
        for (double value : new double[]{Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY}) {
            ControlCommandRequest request = new ControlCommandRequest();
            request.setLinearX(value);
            StepVerifier.create(service.sendVelocity(request)).expectError(IllegalArgumentException.class).verify();
        }
        verifyNoInteractions(topics);
    }

    @Test
    void stationStopLatchesAndKeepsSendingZero() {
        RosTopicService topics = mock(RosTopicService.class);
        OfflineTelemetryService offline = mock(OfflineTelemetryService.class);
        when(topics.publishEmergencyStop(anyString())).thenReturn(Mono.empty());
        when(topics.publishStop(anyString())).thenReturn(Mono.empty());
        ControlService service = new ControlService(new SafetyProperties(), topics,
            mock(DiagnosticsService.class), offline);
        StepVerifier.create(service.emergencyStop()).verifyComplete();
        StepVerifier.create(service.sendVelocity(new ControlCommandRequest())).expectError(IllegalStateException.class).verify();
        service.maintainStop();
        service.maintainStop();
        verify(topics, times(2)).publishStop("station-latched");
        verify(offline).stop();
    }
}
