package com.fishbot.station.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.fishbot.station.config.SafetyProperties;
import com.fishbot.station.domain.ControlCommandRequest;

import reactor.core.publisher.Mono;

@Service
public class ControlService {

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
        double clampedLinear = clamp(request.getLinearX(), safetyProperties.getMaxLinearSpeed());
        double clampedAngular = clamp(request.getAngularZ(), safetyProperties.getMaxAngularSpeed());
        offlineTelemetryService.applyCommand(clampedLinear, clampedAngular);
        return rosTopicService.publishCmdVel(clampedLinear, clampedAngular, request.getSource(), request.getSequence())
                .doOnError(err -> {
                    diagnosticsService.recordError("control", "cmd_vel failure: " + err.getMessage());
                    log.warn("Failed to publish cmd_vel", err);
                });
    }

    public Mono<Void> stop() {
        offlineTelemetryService.stop();
        return rosTopicService.publishStop("operator")
                .doOnError(err -> diagnosticsService.recordError("control", "stop failure: " + err.getMessage()));
    }

    public Mono<Void> emergencyStop() {
        return rosTopicService.publishEmergencyStop("emergency")
                .doOnError(err -> diagnosticsService.recordError("control", "emergency stop failure: " + err.getMessage()));
    }

    private double clamp(double value, double limit) {
        return Math.max(-limit, Math.min(limit, value));
    }
}
