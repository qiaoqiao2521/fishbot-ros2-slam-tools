package com.fishbot.station.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import java.util.concurrent.atomic.AtomicBoolean;

import com.fishbot.station.config.SafetyProperties;
import com.fishbot.station.domain.ControlCommandRequest;

import reactor.core.publisher.Mono;

@Service
public class ControlService {
    private final AtomicBoolean stopLatched = new AtomicBoolean(false);

    private static final Logger log = LoggerFactory.getLogger(ControlService.class);

    private final SafetyProperties safetyProperties;
    private final RosTopicService rosTopicService;
    private final DiagnosticsService diagnosticsService;
    private final OfflineTelemetryService offlineTelemetryService;

    public ControlService(SafetyProperties safetyProperties,
            RosTopicService rosTopicService,
            DiagnosticsService diagnosticsService,
            OfflineTelemetryService offlineTelemetryService) {
        this.safetyProperties = safetyProperties;
        this.rosTopicService = rosTopicService;
        this.diagnosticsService = diagnosticsService;
        this.offlineTelemetryService = offlineTelemetryService;
    }

    public Mono<Void> sendVelocity(ControlCommandRequest request) {
        return Mono.defer(() -> {
        synchronized (stopLatched) {
        if (stopLatched.get()) return Mono.error(new IllegalStateException("Station stop is latched; restart the station after checking other velocity publishers"));
        if (!Double.isFinite(request.getLinearX()) || !Double.isFinite(request.getAngularZ())) {
            return Mono.error(new IllegalArgumentException("Velocity must be finite"));
        }
        double clampedLinear = clamp(request.getLinearX(), safetyProperties.getMaxLinearSpeed());
        double clampedAngular = clamp(request.getAngularZ(), safetyProperties.getMaxAngularSpeed());
        offlineTelemetryService.applyCommand(clampedLinear, clampedAngular);
        return rosTopicService.publishCmdVel(clampedLinear, clampedAngular, request.getSource(), request.getSequence())
                .doOnError(err -> {
                    diagnosticsService.recordError("control", "cmd_vel failure: " + err.getMessage());
                    log.warn("Failed to publish cmd_vel", err);
                });
        }
        });
    }

    public Mono<Void> stop() {
        offlineTelemetryService.stop();
        return rosTopicService.publishStop("operator")
                .doOnError(err -> diagnosticsService.recordError("control", "stop failure: " + err.getMessage()));
    }

    public Mono<Void> emergencyStop() {
        synchronized (stopLatched) {
        stopLatched.set(true);
        offlineTelemetryService.stop();
        return rosTopicService.publishEmergencyStop("emergency")
                .doOnError(err -> diagnosticsService.recordError("control", "emergency stop failure: " + err.getMessage()));
        }
    }

    private double clamp(double value, double limit) {
        if (!Double.isFinite(limit) || limit <= 0) throw new IllegalArgumentException("Invalid speed limit");
        return Math.max(-limit, Math.min(limit, value));
    }

    // Software station hold only; a downstream arbiter/hardware stop is required
    // to exclude velocity publishers outside this process.
    @Scheduled(fixedDelay = 100)
    public void maintainStop() {
        if (stopLatched.get()) rosTopicService.publishStop("station-latched")
            .subscribe(null, error -> log.warn("Latched stop publish failed", error));
    }
}
