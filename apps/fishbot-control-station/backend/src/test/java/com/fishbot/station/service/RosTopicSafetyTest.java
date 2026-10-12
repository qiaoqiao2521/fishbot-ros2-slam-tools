package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.assertThrows;
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
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), new StationRuntimeProperties(), mock(NavigationStateService.class), new RosTimeService(new StationRuntimeProperties(), client));
        Mono<Void> queued = service.publishCmdVel(0.2, 0, "test", 1);
        service.publishEmergencyStop("test").block();
        StepVerifier.create(queued).expectError(IllegalStateException.class).verify();
        verify(client, never()).send(contains("0.200"));
        verify(client).send(contains("\"op\":\"publish\""));
    }

    @Test
    void goalPoseIsRejectedAfterLatch() {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.send(anyString())).thenReturn(Mono.empty());
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), new StationRuntimeProperties(), mock(NavigationStateService.class), new RosTimeService(new StationRuntimeProperties(), client));
        Mono<Void> queued = service.publishGoalPose(1.5, -0.5, 0.0, "test");
        service.publishEmergencyStop("test").block();
        StepVerifier.create(queued).expectError(IllegalStateException.class).verify();
        verify(client, never()).send(contains("\"topic\":\"/goal_pose\",\"msg\""));
    }

    @Test
    void goalPosePublishesPoseStampedInMapFrame() {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.send(anyString())).thenReturn(Mono.empty());
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), new StationRuntimeProperties(), mock(NavigationStateService.class), new RosTimeService(new StationRuntimeProperties(), client));
        StepVerifier.create(service.publishGoalPose(1.25, 2.5, Math.PI, "operator")).verifyComplete();
        verify(client).send(contains("\"op\":\"advertise\",\"topic\":\"/goal_pose\""));
        verify(client).send(contains("\"op\":\"publish\",\"topic\":\"/goal_pose\""));
        verify(client).send(contains("\"frame_id\":\"map\""));
        verify(client).send(contains("\"x\":1.250"));
        verify(client).send(contains("\"y\":2.500"));
        verify(client).send(contains("\"z\":1.0000"));
        verify(client).send(contains("\"w\":0.0000"));
    }

    @Test
    void goalPoseRejectsNonFiniteCoordinates() {
        RosTopicService service = new RosTopicService(mock(RosbridgeClient.class), mock(DiagnosticsService.class), new StationRuntimeProperties(), mock(NavigationStateService.class), mock(RosTimeService.class));
        assertThrows(IllegalArgumentException.class, () -> service.publishGoalPose(Double.NaN, 0, 0, "test"));
    }
}
