# Isolated simulation API

Python ROS bridge binds `127.0.0.1:9070`. Existing React Vite server proxies `/sim-api` there; existing Java `/api` stays as configured. ROS domain 93 and localhost discovery are mandatory. No velocity command endpoint.

## GET /sim-api/state

```json
{"mode":"mujoco","domain":93,"ready":false,"reason":"等待导航就绪","pose":null,"truth":null,"path":[],"home":{"x":0,"y":0,"yaw":0},"mission":{"id":"","status":"idle","current_index":0,"waypoints":[],"return_home":true,"message":"尚未开始"},"obstacle":{"state":"parked","x":-0.7,"y":-0.7,"size":0.36}}
```

Ready pose is `{x,y,yaw}` from AMCL. Independent physical `truth` is `{x,y,yaw,linear_speed,angular_speed}`. Path points are `{x,y}` in map frame. Status is `idle|running|canceling|canceled|succeeded|failed`, reflecting actual action feedback/result. Extra diagnostic fields are allowed. `current_index` is zero-based and includes the return-home point when appended; the displayed waypoint array must match the executed list. Never display terminal success from HTTP acceptance alone.

## GET /sim-api/map

Actual ROS OccupancyGrid: `{width,height,resolution,origin:[x,y,yaw],data:number[]}`. Data is row-major, x increasing within each row, y increasing across rows; unknown is -1, free 0, occupied 100. HTTP 503 when no fresh map has arrived. Canvas converts world/grid coordinates with origin rotation and flips y for screen coordinates.

## POST /sim-api/mission

Body `{waypoints:[{x,y,yaw}],return_home:true,issued_at:Date.now()/1000}`; yaw defaults to 0 if omitted. Sender Unix timestamp is required: reject requests over 3 seconds old or more than 1 second in the future; queued mutations also expire before execution after 2 seconds. One to twelve finite, map-bounded, footprint-clear user points (optional home is a thirteenth executed point); reject overlap with running/canceling mission. Execute Nav2 FollowWaypoints and append launch home `(0,0,0)` if requested. A successful HTTP response acknowledges submission only and is followed by actual asynchronous status.

## POST /sim-api/cancel

Body `{}`. Request actual Nav2 cancellation; retain `canceling` until action acknowledgement/terminal result. The final physical stopped velocity is verified independently. Cancel when idle/terminal may be an idempotent acknowledgement.

## POST /sim-api/obstacle

Body `{action:"block"}` or `{action:"clear"}`. Dispatch to `/sim/obstacle/block_path` or `/sim/obstacle/clear` using std_srvs/Trigger. The actor is the actual MuJoCo body `moving_obstacle`; no robot teleport or fabricated scan. Physics node publishes `/sim/obstacle/state` std_msgs/String JSON `{state,x,y,size}` with state `parked|moving|blocking|returning|error`. Coordinates may both be null while physical truth is stale; preserve ready/reason and hide the actor rather than rejecting the entire status. Its free-joint truth is included in `/ground_truth/free_joint_states`.

## Errors and concurrency

Non-2xx errors return `{error:string}`. Reject invalid/oversized request bodies and non-local origins. HTTP commands enter the ROS executor through a queue, with a finite response deadline; handlers do not spin a ROS node concurrently. Readiness requires advancing/fresh clock and fresh sensors/truth, required TF, active lifecycle servers and FollowWaypoints action readiness. UI polls state about four times per second, preserves the last valid state as stale on connection loss, disables command buttons and shows the reason.
