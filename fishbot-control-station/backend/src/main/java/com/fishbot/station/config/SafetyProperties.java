package com.fishbot.station.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "safety")
public class SafetyProperties {

    private double maxLinearSpeed = 0.3;
    private double maxAngularSpeed = 1.0;
    private long stopCommandDelayMs = 500;

    public double getMaxLinearSpeed() {
        return maxLinearSpeed;
    }

    public void setMaxLinearSpeed(double maxLinearSpeed) {
        this.maxLinearSpeed = maxLinearSpeed;
    }

    public double getMaxAngularSpeed() {
        return maxAngularSpeed;
    }

    public void setMaxAngularSpeed(double maxAngularSpeed) {
        this.maxAngularSpeed = maxAngularSpeed;
    }

    public long getStopCommandDelayMs() {
        return stopCommandDelayMs;
    }

    public void setStopCommandDelayMs(long stopCommandDelayMs) {
        this.stopCommandDelayMs = stopCommandDelayMs;
    }
}
