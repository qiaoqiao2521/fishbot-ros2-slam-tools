package com.fishbot.station.service;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicReference;

import org.springframework.stereotype.Service;

import com.fishbot.station.domain.RobotStateSnapshot;
import com.fasterxml.jackson.databind.JsonNode;

@Service
public class RobotStateService {

    private final AtomicReference<RobotStateSnapshot> currentState = new AtomicReference<>(
            new RobotStateSnapshot(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, Instant.EPOCH));

    public RobotStateSnapshot getCurrentState() {
        return currentState.get();
    }

    public void updateState(RobotStateSnapshot snapshot) {
        currentState.set(snapshot);
    }

    public void updateFromOdom(JsonNode msg, Instant timestamp) {
        currentState.updateAndGet(current -> new RobotStateSnapshot(
                read(msg, "pose", "pose", "position", "x", current.getX()),
                read(msg, "pose", "pose", "position", "y", current.getY()),
                yawFromQuaternion(msg.path("pose").path("pose").path("orientation"), current.getYaw()),
                read(msg, "twist", "twist", "linear", "x", current.getLinearVelocity()),
                read(msg, "twist", "twist", "angular", "z", current.getAngularVelocity()),
                current.getAccelX(),
                current.getAccelY(),
                current.getAccelZ(),
                current.getAngularVelX(),
                current.getAngularVelY(),
                current.getAngularVelZ(),
                current.getRoll(),
                current.getPitch(),
                timestamp));
    }

    public void updateFromImu(JsonNode msg, Instant timestamp) {
        JsonNode orientation = msg.path("orientation");
        double[] rpy = rpyFromQuaternion(orientation, currentState.get().getRoll(), currentState.get().getPitch(), currentState.get().getYaw());
        currentState.updateAndGet(current -> new RobotStateSnapshot(
                current.getX(),
                current.getY(),
                rpy[2],
                current.getLinearVelocity(),
                current.getAngularVelocity(),
                read(msg, "linear_acceleration", "x", current.getAccelX()),
                read(msg, "linear_acceleration", "y", current.getAccelY()),
                read(msg, "linear_acceleration", "z", current.getAccelZ()),
                read(msg, "angular_velocity", "x", current.getAngularVelX()),
                read(msg, "angular_velocity", "y", current.getAngularVelY()),
                read(msg, "angular_velocity", "z", current.getAngularVelZ()),
                rpy[0],
                rpy[1],
                timestamp));
    }

    private static double read(JsonNode node, Object... pathAndFallback) {
        double fallback = (double) pathAndFallback[pathAndFallback.length - 1];
        JsonNode current = node;
        for (int i = 0; i < pathAndFallback.length - 1; i++) {
            current = current.path((String) pathAndFallback[i]);
        }
        return current.isNumber() ? current.asDouble() : fallback;
    }

    private static double yawFromQuaternion(JsonNode orientation, double fallback) {
        return rpyFromQuaternion(orientation, 0.0, 0.0, fallback)[2];
    }

    private static double[] rpyFromQuaternion(JsonNode orientation, double fallbackRoll, double fallbackPitch, double fallbackYaw) {
        if (!orientation.path("x").isNumber()
                || !orientation.path("y").isNumber()
                || !orientation.path("z").isNumber()
                || !orientation.path("w").isNumber()) {
            return new double[] {fallbackRoll, fallbackPitch, fallbackYaw};
        }

        double x = orientation.path("x").asDouble();
        double y = orientation.path("y").asDouble();
        double z = orientation.path("z").asDouble();
        double w = orientation.path("w").asDouble();

        double sinrCosp = 2.0 * (w * x + y * z);
        double cosrCosp = 1.0 - 2.0 * (x * x + y * y);
        double roll = Math.atan2(sinrCosp, cosrCosp);

        double sinp = 2.0 * (w * y - z * x);
        double pitch = Math.abs(sinp) >= 1.0 ? Math.copySign(Math.PI / 2.0, sinp) : Math.asin(sinp);

        double sinyCosp = 2.0 * (w * z + x * y);
        double cosyCosp = 1.0 - 2.0 * (y * y + z * z);
        double yaw = Math.atan2(sinyCosp, cosyCosp);

        return new double[] {roll, pitch, yaw};
    }
}
