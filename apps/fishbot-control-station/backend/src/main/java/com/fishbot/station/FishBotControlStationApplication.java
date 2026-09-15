package com.fishbot.station;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableScheduling;

import com.fishbot.station.config.RosbridgeChannelsProperties;
import com.fishbot.station.config.SafetyProperties;
import com.fishbot.station.config.StationRuntimeProperties;

@SpringBootApplication
@EnableConfigurationProperties({RosbridgeChannelsProperties.class, SafetyProperties.class, StationRuntimeProperties.class})
@EnableScheduling
public class FishBotControlStationApplication {

    public static void main(String[] args) {
        SpringApplication.run(FishBotControlStationApplication.class, args);
    }
}
