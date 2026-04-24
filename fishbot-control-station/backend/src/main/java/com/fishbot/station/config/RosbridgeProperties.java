package com.fishbot.station.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rosbridge")
public class RosbridgeProperties {

    private String host = "localhost";
    private int port = 9090;
    private String path = "/";
    private long reconnectDelayMs = 5000;

    public String getHost() {
        return host;
    }

    public void setHost(String host) {
        this.host = host;
    }

    public int getPort() {
        return port;
    }

    public void setPort(int port) {
        this.port = port;
    }

    public String getPath() {
        return path;
    }

    public void setPath(String path) {
        this.path = path;
    }

    public long getReconnectDelayMs() {
        return reconnectDelayMs;
    }

    public void setReconnectDelayMs(long reconnectDelayMs) {
        this.reconnectDelayMs = reconnectDelayMs;
    }

    public String getUrl() {
        var normalizedPath = path.startsWith("/") ? path : "/" + path;
        return String.format("ws://%s:%d%s", host, port, normalizedPath);
    }
}
