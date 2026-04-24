package com.fishbot.station.config;

public class RosbridgeEndpointProperties {

    private String host = "localhost";
    private int port = 9090;
    private String path = "/";

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

    public String getUrl() {
        String normalizedPath = path.startsWith("/") ? path : "/" + path;
        return String.format("ws://%s:%d%s", host, port, normalizedPath);
    }
}
