package com.fishbot.station.service;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicReference;

import jakarta.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.domain.RobotStateSnapshot;

@Service
public class OfflineTelemetryService {

    private static final Logger log = LoggerFactory.getLogger(OfflineTelemetryService.class);
    private static final double GRAVITY = 9.81;

    private final StationRuntimeProperties runtimeProperties;
    private final RobotStateService robotStateService;
    private final AtomicReference<MotionCommand> command = new AtomicReference<>(new MotionCommand(0.0, 0.0));
    private final AtomicReference<Instant> lastTick = new AtomicReference<>(Instant.now());

    public OfflineTelemetryService(StationRuntimeProperties runtimeProperties, RobotStateService robotStateService) {
        this.runtimeProperties = runtimeProperties;
        this.robotStateService = robotStateService;
    }

    @PostConstruct
    public void announceMode() {
        if (runtimeProperties.isOfflineTelemetry()) {
            log.info("Offline telemetry mode enabled");
        }
    }

    public boolean isEnabled() {
        return runtimeProperties.isOfflineTelemetry();
    }

    public void applyCommand(double linearX, double angularZ) {
        if (!isEnabled()) {
            return;
        }
        command.set(new MotionCommand(linearX, angularZ));
    }

    public void stop() {
        applyCommand(0.0, 0.0);
    }

    @Scheduled(fixedDelayString = "${station.runtime.offline-tick-ms:100}")
    public void tick() {
        if (!isEnabled()) {
            return;
        }

        Instant now = Instant.now();
        Instant previousTick = lastTick.getAndSet(now);
        double dt = Duration.between(previousTick, now).toMillis() / 1000.0;
        if (dt <= 0.0 || dt > 0.5) {
            dt = runtimeProperties.getOfflineTickMs() / 1000.0;
        }

        MotionCommand target = command.get();
        RobotStateSnapshot current = robotStateService.getCurrentState();

        double previousLinear = current.getLinearVelocity();
        double previousAngular = current.getAngularVelocity();
        double newYaw = current.getYaw() + target.angularZ() * dt;
        double avgYaw = current.getYaw() + (target.angularZ() * dt * 0.5);
        double newX = current.getX() + target.linearX() * Math.cos(avgYaw) * dt;
        double newY = current.getY() + target.linearX() * Math.sin(avgYaw) * dt;
        double accelX = (target.linearX() - previousLinear) / Math.max(dt, 1e-6);
        double angularAccel = (target.angularZ() - previousAngular) / Math.max(dt, 1e-6);

        robotStateService.updateState(new RobotStateSnapshot(
                newX,
                newY,
                newYaw,
                target.linearX(),
                target.angularZ(),
                accelX,
                0.0,
                GRAVITY,
                0.0,
                0.0,
                target.angularZ(),
                0.0,
                0.0,
                now));

        if (Math.abs(angularAccel) > 1e-6) {
            log.debug("Offline telemetry angular acceleration {}", angularAccel);
        }
    }

    private record MotionCommand(double linearX, double angularZ) {
    }
}
