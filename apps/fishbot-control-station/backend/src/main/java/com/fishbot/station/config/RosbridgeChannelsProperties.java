package com.fishbot.station.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "station.rosbridge")
public class RosbridgeChannelsProperties {

    private final RosbridgeEndpointProperties control = new RosbridgeEndpointProperties();
    private final RosbridgeEndpointProperties laser = new RosbridgeEndpointProperties();

    public RosbridgeChannelsProperties() {
        control.setPort(9090);
        laser.setPort(9091);
    }

    public RosbridgeEndpointProperties getControl() {
        return control;
    }

    public RosbridgeEndpointProperties getLaser() {
        return laser;
    }
}
