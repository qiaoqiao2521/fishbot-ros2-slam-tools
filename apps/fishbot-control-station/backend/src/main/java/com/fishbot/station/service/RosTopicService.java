package com.fishbot.station.service;

import java.time.Instant;
import java.util.Locale;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.ros.RosbridgeClient;

import reactor.core.publisher.Mono;

@Service
public class RosTopicService {
    private final Object commandGate = new Object();
    private boolean stopLatched;

    private final RosbridgeClient client;
    private final DiagnosticsService diagnosticsService;
    private final StationRuntimeProperties runtimeProperties;

    public RosTopicService(@Qualifier("controlRosbridgeClient") RosbridgeClient client,
                           DiagnosticsService diagnosticsService,
                           StationRuntimeProperties runtimeProperties) {
        this.client = client;
        this.diagnosticsService = diagnosticsService;
        this.runtimeProperties = runtimeProperties;
    }

    public Mono<Void> publishCmdVel(double linearX, double angularZ, String source, long sequence) {
        String payload = buildTwistPayload(linearX, angularZ);
        diagnosticsService.recordCommand(source, "cmd_vel:" + payload + " seq:" + sequence);
        if (runtimeProperties.isOfflineTelemetry()) {
            return Mono.empty();
        }
        return advertise().then(Mono.defer(() -> {
            synchronized (commandGate) {
                if (stopLatched) return Mono.error(new IllegalStateException("Station stop is latched"));
                return client.send(payload);
            }
        }));
    }

    public Mono<Void> publishStop(String reason) {
        diagnosticsService.recordCommand("control", "stop -" + reason + " @ " + Instant.now());
        if (runtimeProperties.isOfflineTelemetry()) {
            return Mono.empty();
        }
        return advertise().then(Mono.defer(() -> client.send(buildTwistPayload(0, 0))));
    }

    public Mono<Void> publishEmergencyStop(String reason) {
        synchronized (commandGate) {
            stopLatched = true;
        }
        diagnosticsService.recordError("emergency-stop", reason);
        return publishStop("emergency");
    }

    private String buildTwistPayload(double linearX, double angularZ) {
        if (!Double.isFinite(linearX) || !Double.isFinite(angularZ)) throw new IllegalArgumentException("Velocity must be finite");
        return String.format(Locale.ROOT, "{\"op\":\"publish\",\"topic\":\"/cmd_vel\",\"msg\":{\"linear\":{\"x\":%.3f,\"y\":0,\"z\":0},\"angular\":{\"x\":0,\"y\":0,\"z\":%.3f}}}",
                linearX, angularZ);
    }

    private Mono<Void> advertise() {
        return client.send("{\"op\":\"advertise\",\"topic\":\"/cmd_vel\",\"type\":\"geometry_msgs/Twist\"}");
    }
}
