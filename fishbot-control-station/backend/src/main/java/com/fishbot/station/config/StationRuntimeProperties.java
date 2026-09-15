package com.fishbot.station.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "station.runtime")
public class StationRuntimeProperties {

    private String telemetryMode = "rosbridge";
    private long offlineTickMs = 100;

    public String getTelemetryMode() {
        return telemetryMode;
    }

    public void setTelemetryMode(String telemetryMode) {
        this.telemetryMode = telemetryMode;
    }

    public long getOfflineTickMs() {
        return offlineTickMs;
    }

    public void setOfflineTickMs(long offlineTickMs) {
        this.offlineTickMs = offlineTickMs;
    }

    public boolean isOfflineTelemetry() {
        return "offline".equalsIgnoreCase(telemetryMode);
    }
}
