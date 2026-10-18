package com.fishbot.station.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.web.reactive.server.WebTestClient;

import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.web.ControlController;
import com.fishbot.station.web.RuntimeController;
import com.fishbot.station.web.RuntimeIdentityFilter;

import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class RuntimeContractTest {
    private WebTestClient client(ControlService owner, StationRuntimeProperties properties) {
        return WebTestClient.bindToController(new RuntimeController(new RuntimeService(properties)),
                new ControlController(owner)).webFilter(new RuntimeIdentityFilter()).build();
    }

    @Test
    void discoveryDoesNotCallOwnerAndDoesNotGuessRemoteDomainOrWorld() {
        ControlService owner = mock(ControlService.class);
        var client = client(owner, new StationRuntimeProperties());
        client.get().uri("/api/v1/runtime").exchange().expectStatus().isOk()
                .expectHeader().valueEquals(RuntimeService.INSTANCE_HEADER, RuntimeService.instanceId())
                .expectHeader().valueEquals(HttpHeaders.CACHE_CONTROL, "no-store")
                .expectBody().jsonPath("$.schema_version").isEqualTo(1)
                .jsonPath("$.instance_id").isEqualTo(RuntimeService.instanceId())
                .jsonPath("$.service").isEqualTo("station")
                .jsonPath("$.mode").isEqualTo("unknown")
                .jsonPath("$.domain").isEmpty().jsonPath("$.scene_id").isEmpty()
                .jsonPath("$.episode_id").isEmpty()
                .jsonPath("$.capabilities[1].submission").isEqualTo("read_only")
                .jsonPath("$.capabilities[1].available").isEqualTo(false)
                .jsonPath("$.capabilities[1].task_lookup").isEqualTo(false)
                .jsonPath("$.capabilities[1].cancel").isEqualTo(false);
        verifyNoInteractions(owner);
        var offline = new StationRuntimeProperties();
        offline.setTelemetryMode("offline");
        assertEquals("offline", new RuntimeService(offline).snapshot().get("mode"));
        assertEquals(RuntimeService.instanceId(), new RuntimeService(offline).snapshot().get("instance_id"));
    }

    @Test
    void staleAndDuplicateHeadersRejectBeforeControlOwnerAndLegacyStillWorks() {
        ControlService owner = mock(ControlService.class);
        when(owner.sendNavigationGoal(any())).thenReturn(Mono.empty());
        var client = client(owner, new StationRuntimeProperties());
        for (String path : List.of("goal", "initial-pose", "cmd-vel", "stop", "emergency-stop")) {
            client.post().uri("/api/v1/control/" + path).header(RuntimeService.INSTANCE_HEADER, "old-instance")
                    .contentType(MediaType.APPLICATION_JSON).bodyValue(Map.of("x", 0, "y", 0, "yaw", 0))
                    .exchange().expectStatus().isEqualTo(409)
                    .expectHeader().valueEquals(RuntimeService.INSTANCE_HEADER, RuntimeService.instanceId())
                    .expectHeader().valueEquals(HttpHeaders.CACHE_CONTROL, "no-store")
                    .expectBody().jsonPath("$.error").isEqualTo("runtime_changed")
                    .jsonPath("$.outcome").isEqualTo("rejected");
        }
        client.post().uri("/api/v1/control/goal")
                .header(RuntimeService.INSTANCE_HEADER, RuntimeService.instanceId(), RuntimeService.instanceId())
                .exchange().expectStatus().isEqualTo(409);
        verifyNoInteractions(owner);
        for (boolean fenced : List.of(false, true)) {
            var request = client.post().uri("/api/v1/control/goal");
            if (fenced) request.header(RuntimeService.INSTANCE_HEADER, RuntimeService.instanceId());
            request.contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(Map.of("x", 0, "y", 0, "yaw", 0, "source", "test"))
                    .exchange().expectStatus().isOk();
        }
        verify(owner, times(2)).sendNavigationGoal(any());
    }

    @Test
    void validationAndUnknownRoutesRetainIdentityAndReadOnlyIgnoresOldFence() {
        ControlService owner = mock(ControlService.class);
        var client = client(owner, new StationRuntimeProperties());
        client.post().uri("/api/v1/control/goal").contentType(MediaType.APPLICATION_JSON).bodyValue(Map.of())
                .exchange().expectStatus().isBadRequest()
                .expectHeader().valueEquals(RuntimeService.INSTANCE_HEADER, RuntimeService.instanceId())
                .expectHeader().valueEquals(HttpHeaders.CACHE_CONTROL, "no-store");
        client.get().uri("/api/v1/runtime").header(RuntimeService.INSTANCE_HEADER, "old")
                .exchange().expectStatus().isOk();
        client.get().uri("/api/v1/not-a-route").exchange().expectStatus().isNotFound()
                .expectHeader().valueEquals(RuntimeService.INSTANCE_HEADER, RuntimeService.instanceId());
        verifyNoInteractions(owner);
    }

    @Test
    void telemetryEventIdsUseDiscoveryIdentityAndIncreasingSequence() {
        EventStreamService service = new EventStreamService();
        StepVerifier.create(service.stream().take(2))
                .then(() -> { service.publishConnection(null); service.publishConnection(null); })
                .recordWith(java.util.ArrayList::new)
                .expectNextCount(2)
                .consumeRecordedWith(events -> {
                    var ids = events.stream().map(ServerSentEvent::id).toList();
                    String prefix = RuntimeService.instanceId() + ":";
                    assertTrue(ids.get(0).startsWith(prefix));
                    assertTrue(ids.get(1).startsWith(prefix));
                    assertTrue(Long.parseLong(ids.get(1).substring(prefix.length()))
                            > Long.parseLong(ids.get(0).substring(prefix.length())));
                }).expectComplete().verify(Duration.ofSeconds(2));
        assertEquals(0, service.rejectedEmissionCount());
    }
    @Test
    void lastBrowserCanDisconnectThenSubscribeAgain() {
        EventStreamService service = new EventStreamService();
        for (int round = 0; round < 3; round++) {
            StepVerifier.create(service.stream().take(1))
                    .then(() -> service.publishConnection(null))
                    .expectNextCount(1).expectComplete().verify(Duration.ofSeconds(2));
        }
        assertEquals(0, service.rejectedEmissionCount());
    }

}
