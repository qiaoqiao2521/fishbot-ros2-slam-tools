package com.fishbot.station.service;

import static org.mockito.Mockito.anyDouble;
import static org.mockito.Mockito.anyLong;
import static org.mockito.Mockito.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;

import com.fishbot.station.config.SafetyProperties;
import com.fishbot.station.domain.ControlCommandRequest;

import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class ControlServiceTest {

    @Test
    void clampsVelocitiesAndInvokesRosTopic() {
        SafetyProperties safety = new SafetyProperties();
        safety.setMaxLinearSpeed(0.5);
        safety.setMaxAngularSpeed(0.2);

        RosTopicService rosTopicService = mock(RosTopicService.class);
        DiagnosticsService diagnosticsService = mock(DiagnosticsService.class);
        OfflineTelemetryService offlineTelemetryService = mock(OfflineTelemetryService.class);
        when(rosTopicService.publishCmdVel(anyDouble(), anyDouble(), anyString(), anyLong())).thenReturn(Mono.empty());

        ControlService controlService = new ControlService(safety, rosTopicService, diagnosticsService, offlineTelemetryService);
        ControlCommandRequest request = new ControlCommandRequest();
        request.setLinearX(2.0);
        request.setAngularZ(-1.0);
        request.setSource("test");
        request.setSequence(42L);

        StepVerifier.create(controlService.sendVelocity(request))
                .verifyComplete();

        verify(rosTopicService, times(1)).publishCmdVel(0.5, -0.2, "test", 42L);
        verify(offlineTelemetryService, times(1)).applyCommand(0.5, -0.2);
    }
}
