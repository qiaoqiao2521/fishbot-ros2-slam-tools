package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.time.Instant;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.reactive.server.WebTestClient;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fishbot.station.config.SafetyProperties;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.domain.NavigationGoalRequest;
import com.fishbot.station.ros.RosbridgeClient;
import com.fishbot.station.web.ControlController;

import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class NavigationControlTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final Instant timestamp = Instant.parse("2026-10-13T01:00:00Z");

    private RosbridgeClient connectedClient() {
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.isConnected()).thenReturn(true);
        when(client.send(anyString())).thenReturn(Mono.empty());
        return client;
    }

    private JsonNode path(int count) {
        var node = mapper.createObjectNode();
        node.putObject("header").put("frame_id", "map");
        ArrayNode poses = node.putArray("poses");
        for (int index = 0; index < count; index++) {
            var pose = poses.addObject();
            pose.putObject("header").put("frame_id", "map");
            pose.putObject("pose").putObject("position").put("x", index).put("y", -index);
        }
        return node;
    }

    @Test
    void initialPosePayloadUsesCovarianceQuaternionAndObservedSimulationClock() throws Exception {
        StationRuntimeProperties properties = new StationRuntimeProperties();
        properties.setUseSimTime(true);
        RosbridgeClient client = connectedClient();
        RosTimeService time = new RosTimeService(properties, client);
        time.updateClock(mapper.readTree("{\"clock\":{\"sec\":42,\"nanosec\":300000000}}"));
        NavigationStateService navigation = new NavigationStateService(properties, client);
        navigation.updateFromPath(path(3), timestamp);
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), properties, navigation, time);
        StepVerifier.create(service.publishInitialPose(1.25, -2.5, Math.PI, "test")).verifyComplete();
        var messages = ArgumentCaptor.forClass(String.class);
        verify(client, times(2)).send(messages.capture());
        JsonNode advertise = mapper.readTree(messages.getAllValues().get(0));
        assertEquals("geometry_msgs/msg/PoseWithCovarianceStamped", advertise.path("type").asText());
        JsonNode payload = mapper.readTree(messages.getAllValues().get(1));
        assertEquals("/initialpose", payload.path("topic").asText());
        JsonNode msg = payload.path("msg");
        assertEquals("map", msg.path("header").path("frame_id").asText());
        assertEquals(42, msg.path("header").path("stamp").path("sec").asInt());
        assertEquals(300000000, msg.path("header").path("stamp").path("nanosec").asInt());
        assertEquals(1.25, msg.path("pose").path("pose").path("position").path("x").asDouble());
        assertEquals(-2.5, msg.path("pose").path("pose").path("position").path("y").asDouble());
        assertEquals(1., msg.path("pose").path("pose").path("orientation").path("z").asDouble());
        assertEquals(0., msg.path("pose").path("pose").path("orientation").path("w").asDouble());
        JsonNode covariance = msg.path("pose").path("covariance");
        assertEquals(36, covariance.size());
        assertEquals(.25, covariance.get(0).asDouble());
        assertEquals(.25, covariance.get(7).asDouble());
        assertEquals(Math.pow(Math.PI / 12, 2), covariance.get(35).asDouble(), 1e-12);
        assertFalse(navigation.snapshot().path().ready());
        assertFalse(navigation.snapshot().localization().ready());
    }

    @Test
    void offlineInitialPoseUpdatesOnlyPreviewAndClearsOldPreviewPath() {
        StationRuntimeProperties properties = new StationRuntimeProperties();
        properties.setTelemetryMode("offline");
        RosbridgeClient client = mock(RosbridgeClient.class);
        NavigationStateService navigation = new NavigationStateService(properties, client);
        assertTrue(navigation.snapshot().path().ready());
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), properties,
                navigation, new RosTimeService(properties, client));
        StepVerifier.create(service.publishInitialPose(.7, -.2, .5, "test")).verifyComplete();
        var snapshot = navigation.snapshot();
        assertEquals(.7, snapshot.localization().x());
        assertEquals(-.2, snapshot.localization().y());
        assertEquals(.5, snapshot.localization().yaw());
        assertTrue(snapshot.localization().statusMessage().contains("offline"));
        assertTrue(snapshot.localization().statusMessage().contains("no AMCL confirmation"));
        assertFalse(snapshot.path().ready());
        assertFalse(snapshot.navStatus().ready());
        verifyNoInteractions(client);
    }

    @Test
    void queuedInitialPoseCannotPublishAfterStopLatch() {
        StationRuntimeProperties properties = new StationRuntimeProperties();
        RosbridgeClient client = connectedClient();
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), properties,
                mock(NavigationStateService.class), new RosTimeService(properties, client));
        Mono<Void> queued = service.publishInitialPose(1, 2, .5, "test");
        service.publishEmergencyStop("test").block();
        StepVerifier.create(queued).expectError(StationStopLatchedException.class).verify();
        verify(client, never()).send(contains("/initialpose"));
    }

    @Test
    void nonFiniteInitialPoseNeverPublishes() {
        RosbridgeClient client = mock(RosbridgeClient.class);
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), new StationRuntimeProperties(),
                mock(NavigationStateService.class), mock(RosTimeService.class));
        for (double value : new double[]{Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY}) {
            assertThrows(IllegalArgumentException.class, () -> service.publishInitialPose(value, 0, 0, "test"));
            assertThrows(IllegalArgumentException.class, () -> service.publishInitialPose(0, value, 0, "test"));
            assertThrows(IllegalArgumentException.class, () -> service.publishInitialPose(0, 0, value, "test"));
        }
        verifyNoInteractions(client);
    }

    @Test
    void pathSamplingRetainsFirstLastAndOriginalPoseCount() {
        NavigationStateService navigation = new NavigationStateService(new StationRuntimeProperties(), connectedClient());
        navigation.updateFromPath(path(4001), timestamp);
        var snapshot = navigation.snapshot().path();
        assertTrue(snapshot.ready());
        assertEquals("map", snapshot.frameId());
        assertEquals(4001, snapshot.poseCount());
        assertEquals(2000, snapshot.points().size());
        assertEquals(0, snapshot.points().get(0).x());
        assertEquals(4000, snapshot.points().get(1999).x());
        assertEquals(timestamp, snapshot.lastUpdate());
    }

    @Test
    void emptyWrongFrameAndMalformedPathsAllClearPreviousPath() throws Exception {
        NavigationStateService navigation = new NavigationStateService(new StationRuntimeProperties(), connectedClient());
        for (JsonNode invalid : List.of(path(0), mapper.readTree("{\"header\":{\"frame_id\":\"odom\"},\"poses\":[]}"),
                mapper.readTree("{\"header\":{\"frame_id\":\"map\"},\"poses\":[{\"pose\":{\"position\":{\"x\":1}}}]}"))) {
            navigation.updateFromPath(path(3), timestamp);
            assertTrue(navigation.snapshot().path().ready());
            navigation.updateFromPath(invalid, timestamp.plusSeconds(1));
            assertFalse(navigation.snapshot().path().ready());
            assertTrue(navigation.snapshot().path().points().isEmpty());
        }
    }

    @Test
    void invalidUnsampledPointRejectsWholePath() {
        JsonNode data = path(4001);
        ((com.fasterxml.jackson.databind.node.ObjectNode) data.path("poses").get(1).path("pose").path("position")).put("x", Double.NaN);
        NavigationStateService navigation = new NavigationStateService(new StationRuntimeProperties(), connectedClient());
        navigation.updateFromPath(path(3), timestamp);
        navigation.updateFromPath(data, timestamp);
        assertFalse(navigation.snapshot().path().ready());
        assertTrue(navigation.snapshot().path().points().isEmpty());
    }

    @Test
    void disconnectClearsPathAndReconnectDoesNotResurrectIt() {
        RosbridgeClient client = connectedClient();
        NavigationStateService navigation = new NavigationStateService(new StationRuntimeProperties(), client);
        navigation.updateFromPath(path(3), timestamp);
        assertTrue(navigation.snapshot().path().ready());
        when(client.isConnected()).thenReturn(false);
        assertFalse(navigation.snapshot().path().ready());
        assertTrue(navigation.snapshot().path().points().isEmpty());
        when(client.isConnected()).thenReturn(true);
        assertFalse(navigation.snapshot().path().ready());
        navigation.updateFromPath(path(2), timestamp.plusSeconds(1));
        assertTrue(navigation.snapshot().path().ready());
    }

    @Test
    void reconnectBetweenSnapshotsInvalidatesPreviousConnectionPath() {
        RosbridgeClient client = connectedClient();
        when(client.getConnectionGeneration()).thenReturn(1L);
        NavigationStateService navigation = new NavigationStateService(new StationRuntimeProperties(), client);
        navigation.updateFromPath(path(3), timestamp);
        assertTrue(navigation.snapshot().path().ready());
        when(client.getConnectionGeneration()).thenReturn(2L);
        assertFalse(navigation.snapshot().path().ready());
        navigation.updateFromPath(path(2), timestamp.plusSeconds(1));
        assertTrue(navigation.snapshot().path().ready());
    }

    @Test
    void newGoalAndInitialPoseClearPreviousPathEvenWhenSubmissionFails() {
        RosbridgeClient client = connectedClient();
        when(client.send(anyString())).thenReturn(Mono.error(new IllegalStateException("Disconnected")));
        StationRuntimeProperties properties = new StationRuntimeProperties();
        NavigationStateService navigation = new NavigationStateService(properties, client);
        RosTopicService service = new RosTopicService(client, mock(DiagnosticsService.class), properties,
                navigation, new RosTimeService(properties, client));
        navigation.updateFromPath(path(3), timestamp);
        assertTrue(navigation.snapshot().path().ready());
        StepVerifier.create(service.publishGoalPose(1, 2, .5, "test"))
                .expectError(IllegalStateException.class).verify();
        assertTrue(navigation.snapshot().path().points().isEmpty());
        navigation.updateFromPath(path(3), timestamp);
        assertTrue(navigation.snapshot().path().ready());
        StepVerifier.create(service.publishInitialPose(1, 2, .5, "test"))
                .expectError(IllegalStateException.class).verify();
        assertTrue(navigation.snapshot().path().points().isEmpty());
    }

    @Test
    void httpSeparatesBadInputClockLossDisconnectAndStopLatch() {
        ControlService service = mock(ControlService.class);
        WebTestClient client = WebTestClient.bindToController(new ControlController(service)).build();
        String body = "{\"x\":1,\"y\":2,\"yaw\":0.5,\"source\":\"test\"}";
        for (Object[] failure : new Object[][]{
                {new IllegalArgumentException("bad pose"), 400, "invalid_initial_pose"},
                {new RosClockUnavailableException(), 503, "clock_unavailable"},
                {new IllegalStateException("Rosbridge is not connected"), 503, "rosbridge_unavailable"},
                {new StationStopLatchedException(), 409, "station_stop_latched"}}) {
            when(service.sendInitialPose(any())).thenReturn(Mono.error((Throwable) failure[0]));
            client.post().uri("/api/v1/control/initial-pose").header("Content-Type", "application/json")
                    .bodyValue(body).exchange().expectStatus().isEqualTo((int) failure[1])
                    .expectBody().jsonPath("$.error").isEqualTo(failure[2]);
        }
    }

    @Test
    void httpRequiresAllPoseFieldsAndSource() {
        ControlService service = mock(ControlService.class);
        WebTestClient client = WebTestClient.bindToController(new ControlController(service)).build();
        for (String body : List.of("{}", "{\"x\":0,\"y\":0,\"source\":\"test\"}",
                "{\"x\":null,\"y\":0,\"yaw\":0,\"source\":\"test\"}",
                "{\"x\":0,\"y\":0,\"yaw\":0,\"source\":\"\"}")) {
            client.post().uri("/api/v1/control/initial-pose").header("Content-Type", "application/json")
                    .bodyValue(body).exchange().expectStatus().isBadRequest();
        }
        verifyNoInteractions(service);
    }

    @Test
    void controlStopLatchRejectsInitialPoseBeforePublisher() {
        RosTopicService topics = mock(RosTopicService.class);
        when(topics.publishEmergencyStop(any())).thenReturn(Mono.empty());
        ControlService service = new ControlService(new SafetyProperties(), topics,
                mock(DiagnosticsService.class), mock(OfflineTelemetryService.class));
        service.emergencyStop().block();
        NavigationGoalRequest request = new NavigationGoalRequest();
        request.setX(0.); request.setY(0.); request.setYaw(0.); request.setSource("test");
        StepVerifier.create(service.sendInitialPose(request)).expectError(StationStopLatchedException.class).verify();
        verify(topics, never()).publishInitialPose(anyDouble(), anyDouble(), anyDouble(), anyString());
    }
}
