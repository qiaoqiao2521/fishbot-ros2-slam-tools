package com.fishbot.station.service;

import java.time.Instant;

import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;

import com.fishbot.station.domain.ConnectionSnapshot;
import com.fishbot.station.domain.DiagnosticSnapshot;
import com.fishbot.station.domain.EventType;
import com.fishbot.station.domain.NavigationRuntimeSnapshot;
import com.fishbot.station.domain.PerceptionRuntimeSnapshot;
import com.fishbot.station.domain.RobotStateSnapshot;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

@Service
public class EventStreamService {

    private final Sinks.Many<ServerSentEvent<Object>> sink = Sinks.many().multicast().onBackpressureBuffer();

    public Flux<ServerSentEvent<Object>> stream() {
        return sink.asFlux();
    }

    public void publishConnection(ConnectionSnapshot snapshot) {
        publish(EventType.CONNECTION, snapshot);
    }

    public void publishRobotState(RobotStateSnapshot snapshot) {
        publish(EventType.ROBOT_STATE, snapshot);
    }

    public void publishDiagnostic(DiagnosticSnapshot snapshot) {
        publish(EventType.DIAGNOSTIC, snapshot);
    }

    public void publishNavigationState(NavigationRuntimeSnapshot snapshot) {
        publish(EventType.NAVIGATION_STATE, snapshot);
    }

    public void publishPerceptionState(PerceptionRuntimeSnapshot snapshot) {
        publish(EventType.PERCEPTION_STATE, snapshot);
    }

    private void publish(EventType type, Object payload) {
        ServerSentEvent<Object> event = ServerSentEvent.builder(payload)
                .event(type.getValue())
                .id(String.valueOf(Instant.now().toEpochMilli()))
                .build();
        sink.tryEmitNext(event);
    }
}
