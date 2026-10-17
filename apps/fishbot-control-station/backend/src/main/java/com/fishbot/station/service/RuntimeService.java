package com.fishbot.station.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Service;

import com.fishbot.station.config.StationRuntimeProperties;

@Service
public class RuntimeService {
    public static final String INSTANCE_HEADER = "X-Fishbot-Instance";
    private static final String INSTANCE_ID = UUID.randomUUID().toString();
    private final StationRuntimeProperties properties;

    public RuntimeService(StationRuntimeProperties properties) {
        this.properties = properties;
    }

    public static String instanceId() {
        return INSTANCE_ID;
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("schema_version", 1);
        value.put("service", "station");
        value.put("instance_id", instanceId());
        // Rosbridge can point at another host/domain. Local process configuration
        // cannot establish the remote robot's simulation or hardware identity.
        value.put("mode", properties.isOfflineTelemetry() ? "offline" : "unknown");
        value.put("domain", null);
        value.put("scene_id", null);
        value.put("episode_id", null);
        value.put("capabilities", List.of(capability("teleop"), capability("navigation"),
                capability("initial_pose")));
        return value;
    }

    private Map<String, Object> capability(String id) {
        return Map.of("id", id, "submission", "topic_publish", "task_lookup", false,
                "cancel", false, "event_history", "none");
    }
}
