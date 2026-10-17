package com.fishbot.station.service;

import java.util.concurrent.atomic.AtomicLong;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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

    private static final Logger log = LoggerFactory.getLogger(EventStreamService.class);
    private static final AtomicLong sequence = new AtomicLong();
    private final AtomicLong rejectedEmissions = new AtomicLong();

    private final Sinks.Many<ServerSentEvent<Object>> sink = Sinks.many().multicast().onBackpressureBuffer(256, false);

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
                .id(RuntimeService.instanceId() + ":" + sequence.incrementAndGet())
                .build();
        Sinks.EmitResult result = sink.tryEmitNext(event);
        if (result.isFailure()) {
            long count = rejectedEmissions.incrementAndGet();
            if (count == 1 || count % 1000 == 0) {
                log.warn("Telemetry snapshot emission rejected: {} (total {})", result, count);
            }
        }
    }

    public long rejectedEmissionCount() { return rejectedEmissions.get(); }
}
