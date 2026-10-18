package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;

import com.fishbot.station.config.SafetyProperties;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.ros.RosbridgeClient;
import com.fishbot.station.web.ControlController;
import com.fishbot.station.web.RuntimeController;
import com.fishbot.station.web.RuntimeIdentityFilter;

import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class LegacyMotionAdmissionTest {
    @Test
    void defaultHttpWritesAreRejectedBeforeOfflineStateOrPublisher() {
        for (String mode : List.of("rosbridge", "offline")) {
            var properties = new StationRuntimeProperties();
            properties.setTelemetryMode(mode);
            RosTopicService topics = mock(RosTopicService.class);
            OfflineTelemetryService offline = mock(OfflineTelemetryService.class);
            var owner = new ControlService(new SafetyProperties(), topics, mock(DiagnosticsService.class), offline, properties);
            var client = WebTestClient.bindToController(new ControlController(owner),
                    new RuntimeController(new RuntimeService(properties))).webFilter(new RuntimeIdentityFilter()).build();
            for (String endpoint : List.of("cmd-vel", "goal", "initial-pose", "stop", "emergency-stop")) {
                Map<String, Object> body = endpoint.equals("cmd-vel")
                        ? Map.of("linearX", .2, "angularZ", 0, "source", "test", "sequence", 1)
                        : endpoint.equals("goal") || endpoint.equals("initial-pose")
                            ? Map.of("x", 1, "y", 1, "yaw", 0, "source", "test") : Map.of();
                client.post().uri("/api/v1/control/" + endpoint).contentType(MediaType.APPLICATION_JSON)
                        .bodyValue(body).exchange().expectStatus().isEqualTo(409)
                        .expectBody().jsonPath("$.error").isEqualTo("legacy_motion_writes_disabled")
                        .jsonPath("$.outcome").isEqualTo("rejected");
            }
            owner.maintainStop();
            verifyNoInteractions(topics, offline);
            client.get().uri("/api/v1/runtime").exchange().expectStatus().isOk()
                    .expectBody().jsonPath("$.capabilities[0].submission").isEqualTo("read_only")
                    .jsonPath("$.capabilities[0].available").isEqualTo(false)
                    .jsonPath("$.capabilities[0].reason").isEqualTo("legacy_motion_writes_disabled");
        }
    }

    @Test
    void publisherItselfRejectsEveryLegacyWriteByDefault() {
        var properties = new StationRuntimeProperties();
        RosbridgeClient client = mock(RosbridgeClient.class);
        var diagnostics = mock(DiagnosticsService.class);
        var navigation = mock(NavigationStateService.class);
        var topics = new RosTopicService(client, diagnostics, properties, navigation, mock(RosTimeService.class));
        for (Mono<Void> write : List.of(topics.publishCmdVel(.2, 0, "test", 1),
                topics.publishGoalPose(1, 1, 0, "test"), topics.publishInitialPose(1, 1, 0, "test"),
                topics.publishStop("test"), topics.publishEmergencyStop("test"))) {
            StepVerifier.create(write).expectError(LegacyMotionWritesDisabledException.class).verify();
        }
        verifyNoInteractions(client, diagnostics, navigation);
    }

    @Test
    @SuppressWarnings("unchecked")
    void compatibilityAdvertisesOnlyPublicationAndOfflinePreviewStaysReadOnly() {
        var properties = new StationRuntimeProperties();
        properties.setLegacyMotionWritesEnabled(true);
        var capability = ((List<Map<String, Object>>) new RuntimeService(properties).snapshot().get("capabilities")).get(0);
        assertEquals("topic_publish", capability.get("submission"));
        assertEquals(true, capability.get("available"));
        assertEquals(false, capability.get("cancel"));
        assertEquals("legacy_topic_publish_only", capability.get("reason"));
        properties.setTelemetryMode("offline");
        var preview = ((List<Map<String, Object>>) new RuntimeService(properties).snapshot().get("capabilities")).get(0);
        assertEquals("read_only", preview.get("submission"));
        assertEquals("offline_preview_only", preview.get("reason"));
    }

    @Test
    void queuedPublicationIsRejectedIfCompatibilityIsRevokedBeforePublish() {
        var properties = new StationRuntimeProperties();
        properties.setLegacyMotionWritesEnabled(true);
        RosbridgeClient client = mock(RosbridgeClient.class);
        when(client.send(anyString())).thenReturn(Mono.empty());
        var topics = new RosTopicService(client, mock(DiagnosticsService.class), properties,
                mock(NavigationStateService.class), mock(RosTimeService.class));
        Mono<Void> queued = topics.publishCmdVel(.2, 0, "test", 1);
        properties.setLegacyMotionWritesEnabled(false);
        StepVerifier.create(queued).expectError(LegacyMotionWritesDisabledException.class).verify();
        verify(client, never()).send(contains("\"op\":\"publish\""));
    }
}
