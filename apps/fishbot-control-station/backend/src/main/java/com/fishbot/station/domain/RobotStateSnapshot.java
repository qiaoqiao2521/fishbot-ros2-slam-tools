package com.fishbot.station.domain;

import java.time.Instant;

public class RobotStateSnapshot {

    private final double x;
    private final double y;
    private final double yaw;
    private final double linearVelocity;
    private final double angularVelocity;
    private final double accelX;
    private final double accelY;
    private final double accelZ;
    private final double angularVelX;
    private final double angularVelY;
    private final double angularVelZ;
    private final double roll;
    private final double pitch;
    private final Instant timestamp;

    public RobotStateSnapshot(double x,
                              double y,
                              double yaw,
                              double linearVelocity,
                              double angularVelocity,
                              double accelX,
                              double accelY,
                              double accelZ,
                              double angularVelX,
                              double angularVelY,
                              double angularVelZ,
                              double roll,
                              double pitch,
                              Instant timestamp) {
        this.x = x;
        this.y = y;
        this.yaw = yaw;
        this.linearVelocity = linearVelocity;
        this.angularVelocity = angularVelocity;
        this.accelX = accelX;
        this.accelY = accelY;
        this.accelZ = accelZ;
        this.angularVelX = angularVelX;
        this.angularVelY = angularVelY;
        this.angularVelZ = angularVelZ;
        this.roll = roll;
        this.pitch = pitch;
        this.timestamp = timestamp;
    }

    public double getX() {
        return x;
    }

    public double getY() {
        return y;
    }

    public double getYaw() {
        return yaw;
    }

    public double getLinearVelocity() {
        return linearVelocity;
    }

    public double getAngularVelocity() {
        return angularVelocity;
    }

    public double getAccelX() {
        return accelX;
    }

    public double getAccelY() {
        return accelY;
    }

    public double getAccelZ() {
        return accelZ;
    }

    public double getAngularVelX() {
        return angularVelX;
    }

    public double getAngularVelY() {
        return angularVelY;
    }

    public double getAngularVelZ() {
        return angularVelZ;
    }

    public double getRoll() {
        return roll;
    }

    public double getPitch() {
        return pitch;
    }

    public Instant getTimestamp() {
        return timestamp;
    }
}
