package com.fishbot.station.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicLong;

import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Qualifier;

import com.fasterxml.jackson.databind.JsonNode;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fishbot.station.domain.LocalizationRuntimeSnapshot;
import com.fishbot.station.domain.MapCellSnapshot;
import com.fishbot.station.domain.MapRuntimeSnapshot;
import com.fishbot.station.domain.NavStatusRuntimeSnapshot;
import com.fishbot.station.domain.PathRuntimeSnapshot;
import com.fishbot.station.domain.NavigationRuntimeSnapshot;
import com.fishbot.station.domain.TfRuntimeSnapshot;
import com.fishbot.station.ros.RosbridgeClient;

@Service
public class NavigationStateService {

    private static final Instant NEVER = Instant.EPOCH;
    private static final int MAX_MAP_CELLS = 6_000;
    private static final int MAX_PATH_POINTS = 2_000;

    private final AtomicReference<MapRuntimeSnapshot> mapState;
    private final AtomicReference<TfRuntimeSnapshot> tfState;
    private final AtomicReference<LocalizationRuntimeSnapshot> localizationState;
    private final AtomicReference<NavStatusRuntimeSnapshot> navStatusState;
    private final AtomicReference<PathRuntimeSnapshot> pathState;
    private final AtomicLong pathConnectionGeneration = new AtomicLong();
    private final StationRuntimeProperties runtimeProperties;
    private final RosbridgeClient laserClient;

    public NavigationStateService(StationRuntimeProperties runtimeProperties,
            @Qualifier("laserRosbridgeClient") RosbridgeClient laserClient) {
        this.runtimeProperties = runtimeProperties;
        this.laserClient = laserClient;
        boolean offline = runtimeProperties.isOfflineTelemetry();
        this.mapState = new AtomicReference<>(offline ? offlineMapSnapshot() : new MapRuntimeSnapshot(
                false, 0, 0, 0.0, 0.0, 0.0, 0.0, 1, NEVER,
                "waiting for /map",
                List.of()));
        this.tfState = new AtomicReference<>(new TfRuntimeSnapshot(
                false, false, false, 0, 0, NEVER, offline ? "offline simulator: tf feed bypassed" : "waiting for /tf"));
        this.localizationState = new AtomicReference<>(offline ? offlineLocalizationSnapshot() : new LocalizationRuntimeSnapshot(
                false, 0.0, 0.0, 0.0, 0.0, NEVER,
                "waiting for /amcl_pose"));
        this.navStatusState = new AtomicReference<>(new NavStatusRuntimeSnapshot(
                false, 0, 0, "idle", NEVER,
                offline ? "offline simulator: nav action feed bypassed" : "waiting for navigate_to_pose status"));
        this.pathState = new AtomicReference<>(offline
                ? new PathRuntimeSnapshot(true, "map", 3,
                        List.of(new PathRuntimeSnapshot.Point(-1.2, -1),
                                new PathRuntimeSnapshot.Point(0, -1), new PathRuntimeSnapshot.Point(0, 1)),
                        Instant.now(), "offline path preview; no Nav2 planner")
                : emptyPath("", NEVER, "waiting for /plan"));
    }

    public NavigationRuntimeSnapshot snapshot() {
        if (!runtimeProperties.isOfflineTelemetry() && !laserClient.isConnected()) {
            invalidatePath("rosbridge disconnected; path cleared", Instant.now());
        } else if (!runtimeProperties.isOfflineTelemetry() && pathState.get().ready()
                && pathConnectionGeneration.get() != laserClient.getConnectionGeneration()) {
            invalidatePath("rosbridge reconnected; waiting for a new /plan", Instant.now());
        }
        return new NavigationRuntimeSnapshot(
                mapState.get(),
                tfState.get(),
                localizationState.get(),
                navStatusState.get(),
                pathState.get());
    }

    public void updateFromPath(JsonNode msg, Instant timestamp) {
        String frame = msg.path("header").path("frame_id").asText("");
        JsonNode poses = msg.path("poses");
        if (!"map".equals(frame) || !poses.isArray()) {
            pathState.set(emptyPath(frame, timestamp, "invalid /plan frame or payload; path cleared"));
            return;
        }
        for (JsonNode pose : poses) {
            JsonNode position = pose.path("pose").path("position");
            String poseFrame = pose.path("header").path("frame_id").asText("");
            if ((!poseFrame.isEmpty() && !"map".equals(poseFrame))
                    || !position.path("x").isNumber() || !position.path("y").isNumber()
                    || !Double.isFinite(position.path("x").asDouble())
                    || !Double.isFinite(position.path("y").asDouble())) {
                pathState.set(emptyPath(frame, timestamp, "invalid /plan pose; path cleared"));
                return;
            }
        }
        if (poses.isEmpty()) {
            pathState.set(emptyPath(frame, timestamp, "empty /plan; path cleared"));
            return;
        }
        int count = Math.min(MAX_PATH_POINTS, poses.size());
        List<PathRuntimeSnapshot.Point> points = new ArrayList<>(count);
        for (int i = 0; i < count; i++) {
            int index = count == 1 ? 0 : (int) ((long) i * (poses.size() - 1) / (count - 1));
            JsonNode position = poses.path(index).path("pose").path("position");
            points.add(new PathRuntimeSnapshot.Point(position.path("x").asDouble(), position.path("y").asDouble()));
        }
        pathConnectionGeneration.set(laserClient.getConnectionGeneration());
        pathState.set(new PathRuntimeSnapshot(true, frame, poses.size(), List.copyOf(points), timestamp,
                poses.size() > count ? "latest observed /plan sampled" : "latest observed /plan"));
    }

    public void invalidatePath(String reason, Instant timestamp) {
        pathState.set(emptyPath("map", timestamp, reason));
    }

    public void applyOfflineInitialPose(double x, double y, double yaw, Instant timestamp) {
        if (!runtimeProperties.isOfflineTelemetry()) return;
        localizationState.set(new LocalizationRuntimeSnapshot(true, x, y, yaw,
                Math.pow(Math.PI / 12, 2), timestamp, "offline initial pose preview; no AMCL confirmation"));
        invalidatePath("offline initial pose changed; path preview cleared", timestamp);
    }

    private static PathRuntimeSnapshot emptyPath(String frame, Instant timestamp, String message) {
        return new PathRuntimeSnapshot(false, frame, 0, List.of(), timestamp, message);
    }

    public void updateFromMap(JsonNode msg, Instant timestamp) {
        JsonNode info = msg.path("info");
        int width = info.path("width").asInt(0);
        int height = info.path("height").asInt(0);
        double resolution = info.path("resolution").asDouble(0.0);
        JsonNode origin = info.path("origin");
        double originX = origin.path("position").path("x").asDouble(0.0);
        double originY = origin.path("position").path("y").asDouble(0.0);
        double originYaw = yawFromQuaternion(origin.path("orientation"));
        boolean ready = width > 0 && height > 0 && resolution > 0.0;
        int sampleStride = computeSampleStride(width, height);
        List<MapCellSnapshot> sampledCells = ready ? sampleMapCells(msg.path("data"), width, height, sampleStride) : List.of();
        mapState.set(new MapRuntimeSnapshot(
                ready,
                width,
                height,
                resolution,
                originX,
                originY,
                originYaw,
                sampleStride,
                timestamp,
                ready ? "live occupancy grid sampled" : "map payload incomplete",
                sampledCells));
    }

    public void updateFromTf(JsonNode msg, Instant timestamp, boolean isStatic) {
        JsonNode transforms = msg.path("transforms");
        int transformCount = transforms.isArray() ? transforms.size() : 0;
        boolean mapToOdomPresent = false;
        boolean odomToBasePresent = false;

        if (transforms.isArray()) {
            for (JsonNode transform : transforms) {
                String parent = transform.path("header").path("frame_id").asText("");
                String child = transform.path("child_frame_id").asText("");
                if ("map".equals(parent) && "odom".equals(child)) {
                    mapToOdomPresent = true;
                }
                if ("odom".equals(parent) && isBaseFrame(child)) {
                    odomToBasePresent = true;
                }
            }
        }

        TfRuntimeSnapshot current = tfState.get();
        boolean finalMapToOdomPresent = current.mapToOdomPresent() || mapToOdomPresent;
        boolean finalOdomToBasePresent = current.odomToBasePresent() || odomToBasePresent;
        int staticCount = current.staticTransformCount() + (isStatic ? transformCount : 0);
        int totalCount = current.transformCount() + transformCount;

        tfState.set(new TfRuntimeSnapshot(
                totalCount > 0,
                finalMapToOdomPresent,
                finalOdomToBasePresent,
                totalCount,
                staticCount,
                timestamp,
                totalCount > 0 ? "tf graph observed" : "tf payload incomplete"));
    }

    public void updateFromLocalization(JsonNode msg, Instant timestamp) {
        JsonNode pose = msg.path("pose").path("pose");
        double x = pose.path("position").path("x").asDouble(0.0);
        double y = pose.path("position").path("y").asDouble(0.0);
        double yaw = yawFromQuaternion(pose.path("orientation"));
        JsonNode covariance = msg.path("pose").path("covariance");
        double covarianceScore = covariance.isArray() && covariance.size() > 35 ? covariance.path(35).asDouble(0.0) : 0.0;

        localizationState.set(new LocalizationRuntimeSnapshot(
                true,
                x,
                y,
                yaw,
                covarianceScore,
                timestamp,
                "amcl pose locked"));
    }

    public void updateFromNavStatus(JsonNode msg, Instant timestamp) {
        JsonNode statusList = msg.path("status_list");
        int activeGoals = 0;
        int totalGoals = statusList.isArray() ? statusList.size() : 0;
        Map<String, Integer> counts = new LinkedHashMap<>();

        if (statusList.isArray()) {
            for (JsonNode statusNode : statusList) {
                int status = statusNode.path("status").asInt(-1);
                String label = navStatusLabel(status);
                counts.merge(label, 1, Integer::sum);
                if (status == 1 || status == 2 || status == 3) {
                    activeGoals++;
                }
            }
        }

        String summary = counts.isEmpty()
                ? "idle"
                : counts.entrySet().stream()
                        .map(entry -> entry.getKey() + ":" + entry.getValue())
                        .reduce((left, right) -> left + ", " + right)
                        .orElse("idle");

        navStatusState.set(new NavStatusRuntimeSnapshot(
                totalGoals > 0,
                activeGoals,
                totalGoals,
                summary,
                timestamp,
                totalGoals > 0 ? "nav action status observed" : "no active nav goals"));
    }

    private static boolean isBaseFrame(String frame) {
        return "base_footprint".equals(frame) || "base_link".equals(frame);
    }

    // Offline stand-in for /map so the radar scan+map layer stays verifiable
    // without rosbridge: a 10x10 m room with perimeter walls and one pillar.
    private static MapRuntimeSnapshot offlineMapSnapshot() {
        int width = 200;
        int height = 200;
        double resolution = 0.05;
        int stride = 3;
        List<MapCellSnapshot> cells = new ArrayList<>();
        for (int y = 0; y < height; y += stride) {
            for (int x = 0; x < width; x += stride) {
                boolean perimeter = x < stride || y < stride || x >= width - stride || y >= height - stride;
                boolean pillar = x >= 60 && x < 78 && y >= 60 && y < 78;
                if (perimeter || pillar) {
                    cells.add(new MapCellSnapshot(x, y, 100));
                } else if (x >= 100 && x < 130 && y >= 20 && y < 26) {
                    cells.add(new MapCellSnapshot(x, y, 60));
                }
            }
        }
        return new MapRuntimeSnapshot(
                true,
                width,
                height,
                resolution,
                -5.0,
                -5.0,
                0.0,
                stride,
                Instant.now(),
                "offline occupancy grid preview",
                List.copyOf(cells));
    }

    private static LocalizationRuntimeSnapshot offlineLocalizationSnapshot() {
        return new LocalizationRuntimeSnapshot(
                true,
                -1.2,
                -1.0,
                0.0,
                0.04,
                Instant.now(),
                "offline localization preview");
    }

    private static int computeSampleStride(int width, int height) {
        long totalCells = (long) width * height;
        if (totalCells <= 0 || totalCells <= MAX_MAP_CELLS) {
            return 1;
        }

        return Math.max(1, (int) Math.ceil(Math.sqrt((double) totalCells / MAX_MAP_CELLS)));
    }

    private static List<MapCellSnapshot> sampleMapCells(JsonNode data, int width, int height, int stride) {
        if (!data.isArray() || width <= 0 || height <= 0) {
            return List.of();
        }

        List<MapCellSnapshot> cells = new ArrayList<>();
        for (int y = 0; y < height; y += stride) {
            for (int x = 0; x < width; x += stride) {
                int index = (y * width) + x;
                JsonNode valueNode = data.path(index);
                if (!valueNode.isInt()) {
                    continue;
                }
                int occupancy = valueNode.asInt(-1);
                if (occupancy < 0) {
                    continue;
                }
                cells.add(new MapCellSnapshot(x, y, occupancy));
            }
        }
        return List.copyOf(cells);
    }

    private static String navStatusLabel(int status) {
        return switch (status) {
            case 1 -> "ACCEPTED";
            case 2 -> "EXECUTING";
            case 3 -> "CANCELING";
            case 4 -> "SUCCEEDED";
            case 5 -> "CANCELED";
            case 6 -> "ABORTED";
            default -> "UNKNOWN";
        };
    }

    private static double yawFromQuaternion(JsonNode orientation) {
        if (!orientation.path("x").isNumber()
                || !orientation.path("y").isNumber()
                || !orientation.path("z").isNumber()
                || !orientation.path("w").isNumber()) {
            return 0.0;
        }

        double x = orientation.path("x").asDouble();
        double y = orientation.path("y").asDouble();
        double z = orientation.path("z").asDouble();
        double w = orientation.path("w").asDouble();

        double sinyCosp = 2.0 * (w * z + x * y);
        double cosyCosp = 1.0 - 2.0 * (y * y + z * z);
        return Math.atan2(sinyCosp, cosyCosp);
    }
}
