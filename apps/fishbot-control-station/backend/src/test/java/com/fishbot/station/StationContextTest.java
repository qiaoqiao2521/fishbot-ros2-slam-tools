package com.fishbot.station;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = {"station.runtime.telemetry-mode=offline"})
class StationContextTest {
    @Test
    void contextLoadsWithoutBeanOverriding() {}
}
