// Compiled by test_firmware_time_sync.py without ROS, PlatformIO or devices.
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <string>
#include "fishbot_time_sync_policy.h"
#include "firmware_glue_under_test.h"

// Only the resource APIs are substituted. The generated include contains the
// complete production create, destroy, options release and result checker.
namespace lifecycle {
using rcl_ret_t = int;
using rmw_ret_t = int;
constexpr int RCL_RET_OK = 0;
constexpr int RMW_RET_OK = 0;
#define RCSOFTCHECK(fn) ((void)(fn))
#define RCL_MS_TO_NS(value) (value)
#define ROSIDL_GET_MSG_TYPE_SUPPORT(...) 0
#define ROSIDL_GET_SRV_TYPE_SUPPORT(...) 0
constexpr int ON_NEW_DATA = 0;
using String = std::string;
struct Options { bool impl; };
struct rmw_context_t { bool impl; };
struct Context { bool impl; bool valid; rmw_context_t rmw; };
struct rcl_clock_t { bool initialized; };
struct Support { Context context; rcl_clock_t clock; int *allocator; };
struct Node { bool impl; };
struct Publisher { bool impl; };
struct Subscription { bool impl; };
struct Service { bool impl; };
struct Timer { bool impl; };
struct Executor { bool handles; int added; };
struct Header { std::string frame_id; };
struct Message { Header header; std::string child_frame_id; };
static Message odom_msg, imu_msg, twist_msg;
static int config_req, config_res;
static Options init_options = {false};
static bool init_options_owned = false;
static int allocator = 0;
static Support support = {};
static Node node = {};
static Publisher odom_publisher = {}, imu_publisher = {};
static Subscription twist_subscriber = {};
static Service config_service = {};
static Timer timer = {};
static Executor executor = {};
static int options_live = 0, context_copies = 0, failure_stage = 0;
static int publisher_fini_calls[2] = {0, 0};
static int last_init_stage = 0, init_calls = 0, timeout_calls = 0;
static bool partial_context_failure = false;
static bool context_without_rmw_failure = false;
struct Config {
    int ros2_domain_id() { return 0; }
    String ros2_nodename() { return "fishbot"; }
    String ros2_namespace() { return ""; }
    String ros2_twist_topic_name() { return "cmd_vel"; }
    String ros2_odom_topic_name() { return "odom"; }
    String ros2_odom_frameid() { return "odom"; }
    String ros2_odom_child_frameid() { return "base_link"; }
    unsigned int odom_publish_period() { return 50; }
} config;
static bool destory_fishbot_transport();
static void fishlog_debug(const char *, const char *, ...) {}
static void delay(int) {}
static String micro_ros_string_utilities_set(String, const char *value) { return value; }
static int rcl_get_default_allocator() { return 0; }
static void callback_sensor_publisher_timer_() {}
static void callback_twist_subscription_() {}
static void callback_config_service_() {}
static bool init_fails(int stage) {
    last_init_stage = stage; ++init_calls; return failure_stage == stage;
}
static Options rcl_get_zero_initialized_init_options() { return {false}; }
static int rcl_init_options_init(Options *o, int) {
    assert(!o->impl); o->impl = true;
    if (init_fails(1)) return 1; // SDK failure can leave a freed pointer.
    ++options_live; return 0;
}
static int rcl_init_options_fini(Options *o) {
    assert(o->impl && options_live == 1);
    --options_live; return 0; // Humble leaves the caller's pointer unchanged.
}
static int rcl_init_options_set_domain_id(Options *o, int) {
    assert(o->impl); return init_fails(2) ? 1 : 0;
}
static int rclc_support_init_with_options(Support *value, int, void *, Options *o, int *) {
    assert(o->impl && options_live == 1);
    if (init_fails(3)) return 1; // Exact rcl_init failure leaves no context.
    value->context.impl = true;
    value->context.valid = !context_without_rmw_failure;
    value->context.rmw.impl = !context_without_rmw_failure;
    ++context_copies;
    if (partial_context_failure || context_without_rmw_failure) return 1;
    value->clock.initialized = true;
    return 0;
}
template<typename... Args> static int rclc_node_init_default(Node *value, Args...) {
    assert(support.context.valid);
    if (init_fails(4)) return 1;
    value->impl = true; return 0;
}
template<typename... Args> static int rclc_publisher_init_best_effort(Publisher *value, Args...) {
    assert(node.impl);
    if (init_fails(value == &odom_publisher ? 5 : 6)) return 1;
    value->impl = true; return 0;
}
template<typename... Args> static int rclc_subscription_init_best_effort(Subscription *value, Args...) {
    assert(node.impl);
    if (init_fails(7)) return 1;
    value->impl = true; return 0;
}
template<typename... Args> static int rclc_service_init_default(Service *value, Args...) {
    assert(node.impl);
    if (init_fails(8)) return 1;
    value->impl = true; return 0;
}
template<typename... Args> static int rclc_timer_init_default(Timer *value, Args...) {
    assert(support.clock.initialized);
    if (init_fails(9)) return 1;
    value->impl = true; return 0;
}
template<typename... Args> static int rclc_executor_init(Executor *value, Args...) {
    assert(support.context.valid);
    if (init_fails(10)) return 1;
    value->handles = true; value->added = 0; return 0;
}
template<typename... Args> static int rclc_executor_add_subscription(Executor *value, Args...) {
    assert(value->handles && twist_subscriber.impl);
    if (init_fails(11)) return 1;
    ++value->added; return 0;
}
template<typename... Args> static int rclc_executor_add_timer(Executor *value, Args...) {
    assert(value->handles && timer.impl);
    if (init_fails(12)) return 1;
    ++value->added; return 0;
}
template<typename... Args> static int rclc_executor_add_service(Executor *value, Args...) {
    assert(value->handles && config_service.impl);
    if (init_fails(13)) return 1;
    ++value->added; return 0;
}
static rmw_context_t *rcl_context_get_rmw_context(Context *value) {
    assert(value->impl); return &value->rmw;
}
static int rmw_uros_set_context_entity_destroy_session_timeout(rmw_context_t *value, int timeout) {
    assert(value && value->impl && timeout == 0); ++timeout_calls; return 0;
}
static int rclc_executor_fini(Executor *value) {
    assert(value->handles); value->handles = false; value->added = 0; return 0;
}
static int rcl_timer_fini(Timer *value) {
    assert(value->impl && !executor.handles && support.clock.initialized);
    value->impl = false; return 0;
}
static int rcl_publisher_fini(Publisher *value, Node *owner) {
    assert(owner->impl && value->impl && !executor.handles);
    value->impl = false;
    ++publisher_fini_calls[value == &odom_publisher ? 0 : 1]; return 0;
}
static int rcl_subscription_fini(Subscription *value, Node *owner) {
    assert(owner->impl && value->impl && !executor.handles);
    value->impl = false; return 0;
}
static int rcl_service_fini(Service *value, Node *owner) {
    assert(owner->impl && value->impl && !executor.handles);
    value->impl = false; return 0;
}
static int rcl_node_fini(Node *value) {
    assert(value->impl && !odom_publisher.impl && !imu_publisher.impl &&
           !twist_subscriber.impl && !config_service.impl);
    value->impl = false; return 0;
}
static bool rcl_clock_valid(rcl_clock_t *value) { return value->initialized; }
static int rcl_clock_fini(rcl_clock_t *value) {
    assert(value->initialized && !timer.impl); return 0; // Humble does not clear clock type.
}
static bool rcl_context_is_valid(Context *value) { return value->valid; }
static int rcl_shutdown(Context *value) {
    assert(value->impl && value->valid && !node.impl);
    value->valid = false; value->rmw.impl = false; return 0;
}
static int rcl_context_fini(Context *value) {
    assert(value->impl && !value->valid && !node.impl);
    *value = {}; --context_copies; return 0;
}
#include "firmware_lifecycle_under_test.h"
static bool create_options() { return create_fishbot_transport(); }
static void destroy_owned_resources() { assert(destory_fishbot_transport()); }
#undef RCSOFTCHECK
#undef RCL_MS_TO_NS
#undef ROSIDL_GET_MSG_TYPE_SUPPORT
#undef ROSIDL_GET_SRV_TYPE_SUPPORT
}

using Policy = FishbotTimeSyncPolicy;

static void startup()
{
    Policy p;
    assert(p.maintenance_due(0) == Policy::SYNC);
    assert(p.last_success_age_ms(0) == -1);
    assert(!p.motion_allowed(0, 100000));
    assert(!p.accept_stamp(0, 100000));
    p.begin_sync(0);
    p.finish_sync(50, false, 100000);
    assert(p.last_success_age_ms(50) == -1);
    assert(!p.motion_allowed(50, 100000));
    assert(!p.sync_due(4999));
    assert(p.sync_due(5000));
}

static void failure_does_not_renew()
{
    Policy p;
    p.finish_sync(100, true, 100000);
    p.finish_sync(5100, false, 105000);
    p.finish_sync(10100, false, 110000);
    assert(p.last_success_age_ms(10100) == 10000);
    assert(p.last_sync_ms() == 100);
    assert(p.motion_allowed(15099, 114999));
    assert(!p.motion_allowed(15100, 115000));
    assert(!p.accept_stamp(15100, 115000));
    assert(p.last_success_age_ms(15100) == 15000);
}

static void invalid_epoch()
{
    Policy p;
    p.finish_sync(1, true, 0);
    assert(!p.fresh(1));
    p.finish_sync(2, true, -1);
    assert(!p.fresh(2));
    p.finish_sync(3, true, 100000);
    assert(!p.motion_allowed(4, 0));
    assert(!p.accept_stamp(4, -1));
}

static void renewal()
{
    Policy p;
    p.finish_sync(100, true, 100000);
    p.finish_sync(5100, true, 105000);
    assert(p.motion_allowed(20099, 119999));
    assert(!p.motion_allowed(20100, 120000));
    p.finish_sync(21000, true, 121000);
    assert(p.accept_stamp(21000, 121000));
}

static void native_stamps()
{
    Policy p;
    p.finish_sync(0, true, 100000);
    assert(p.accept_stamp(0, 100000));
    assert(!p.accept_stamp(1, 100000));
    assert(p.motion_allowed(1, 100000));
    assert(p.accept_stamp(2, 100001));
    assert(!p.accept_stamp(3, 99999));
    assert(!p.motion_allowed(3, 99999));
    assert(p.accept_stamp(4, 100002));
}

static void backward_sync()
{
    Policy p;
    p.finish_sync(0, true, 100000);
    assert(p.accept_stamp(5000, 105000));
    p.finish_sync(5050, true, 104000);
    assert(!p.motion_allowed(5050, 104000));
    assert(!p.accept_stamp(5050, 104000));
    assert(!p.accept_stamp(6050, 105000));
    assert(p.accept_stamp(6051, 105001));
    assert(p.motion_allowed(6051, 105001));
}

static void reconnect()
{
    Policy p;
    p.finish_sync(0, true, 100000);
    assert(p.accept_stamp(1, 100001));
    p.reset_session(10);
    assert(p.last_success_age_ms(10) == -1);
    assert(!p.motion_allowed(10, 100010));
    assert(p.maintenance_due(10) == Policy::SYNC);
    p.finish_sync(11, true, 99999);
    assert(!p.accept_stamp(11, 99999));
    assert(!p.motion_allowed(11, 99999));
    assert(p.accept_stamp(14, 100002));
}

static void rollover()
{
    Policy p;
    const uint32_t start = std::numeric_limits<uint32_t>::max() - 1000;
    p.reset_session(start);
    p.begin_sync(start);
    p.finish_sync(start, true, 100000);
    assert(!p.sync_due(start + 4999));
    assert(p.sync_due(start + 5000));
    assert(p.motion_allowed(start + 14999, 114999));
    assert(!p.motion_allowed(start + 15000, 115000));
    // Even a later full wrap cannot revive a lease which was observed expired.
    assert(!p.motion_allowed(start + 1, 999999));
}

static void maintenance_budget()
{
    Policy p;
    p.reset_session(0);
    assert(p.maintenance_due(0) == Policy::SYNC);
    p.begin_sync(0);
    assert(p.maintenance_due(4999) == Policy::NONE);
    assert(p.maintenance_due(5000) == Policy::SYNC);
    p.begin_sync(5000);
    // The following pass does not add a separate active-session ping wait.
    assert(p.maintenance_due(5050) == Policy::NONE);
    assert(p.maintenance_due(5150) == Policy::NONE);
    assert(Policy::sync_timeout_ms == 50);
    assert(Policy::ping_timeout_ms <= 100);
}

static void connected_sync_heartbeat()
{
    Policy p;
    p.reset_session(1000);
    p.begin_sync(1000);
    p.finish_sync(1050, true, 100000);
    for (uint32_t now : {6000u, 11000u})
    {
        assert(p.maintenance_due(now) == Policy::SYNC);
        p.begin_sync(now);
        p.finish_sync(now + 50, false, 105000);
        assert(p.maintenance_due(now + 50) == Policy::NONE);
        assert(p.fresh(now + 50));
        assert(!p.reconnect_due(now + 50));
    }
    assert(p.last_sync_ms() == 1050); // Failed heartbeats do not renew the lease.
    assert(p.maintenance_due(16000) == Policy::SYNC);
    p.begin_sync(16000);
    p.finish_sync(16050, false, 115000); // This bounded wait crosses the lease.
    assert(p.maintenance_due(16050) == Policy::RECONNECT);
    assert(!p.fresh(16050));
    assert(!p.motion_allowed(16050, 115000));
}

static void motor_lease()
{
    time_sync.finish_sync(0, true, 100000);
    assert(update_command_clock(14900, 114900));
    command_valid = true;
    command_received_ms = 14900;
    command_targets[0] = 12;
    command_targets[1] = 13;
    fake_millis = 14999;
    sample_motor_targets();
    assert(observed_targets[0] == 12 && observed_targets[1] == 13);
    // No transport task runs here: motor loop independently enforces sync TTL.
    fake_millis = 15000;
    sample_motor_targets();
    assert(observed_targets[0] == 0 && observed_targets[1] == 0);
    assert(!command_valid && !command_clock_valid);
    time_sync.finish_sync(15001, true, 115001);
    assert(update_command_clock(15001, 115001));
    fake_millis = 15001;
    sample_motor_targets();
    assert(observed_targets[0] == 0); // Sync recovery never replays old motion.
}

static void command_watchdog()
{
    time_sync.finish_sync(0, true, 100000);
    assert(update_command_clock(0, 100000));
    command_valid = true;
    command_received_ms = 0;
    command_targets[0] = command_targets[1] = 12;
    fake_millis = 499;
    sample_motor_targets();
    assert(observed_targets[0] == 12);
    fake_millis = 500;
    sample_motor_targets();
    assert(observed_targets[0] == 0 && !command_valid);
}

static void backward_invalidates_motion()
{
    time_sync.finish_sync(0, true, 100000);
    assert(time_sync.accept_stamp(0, 100000));
    assert(update_command_clock(0, 100000));
    command_valid = true;
    command_received_ms = 0;
    command_targets[0] = command_targets[1] = 12;
    time_sync.finish_sync(10, true, 99900);
    assert(!update_command_clock(10, 99900));
    assert(!command_valid);
    fake_millis = 10;
    sample_motor_targets();
    assert(observed_targets[0] == 0);
    assert(update_command_clock(111, 100001));
    sample_motor_targets();
    assert(observed_targets[0] == 0);
}

static void display_snapshot()
{
    const int64_t epoch = INT64_C(1791477694243);
    time_sync.finish_sync(0, true, epoch);
    assert(update_command_clock(0, epoch));
    sample_motor_targets();
    assert(display.stamp == epoch); // Preserve both halves of the real epoch.
    assert(update_command_clock(1, epoch + 1));
    fake_millis = 1;
    sample_motor_targets();
    assert(display.stamp == epoch + 1);
    assert(!update_command_clock(2, 0));
    sample_motor_targets();
    assert(display.stamp == 0);
}

static void reconnect_first_sync_timeout()
{
    Policy p;
    const uint32_t start = 100000;
    p.reset_session(start);
    assert(!p.reconnect_due(start));
    assert(p.maintenance_due(start) == Policy::SYNC);
    for (uint32_t offset : {0u, 5000u, 10000u})
    {
        p.begin_sync(start + offset);
        p.finish_sync(start + offset + 50, false, 900000);
        assert(!p.reconnect_due(start + offset + 50));
    }
    assert(!p.reconnect_due(start + 14999));
    assert(p.maintenance_due(start + 15000) == Policy::RECONNECT);
    assert(p.maintenance_due(start + 15001) == Policy::RECONNECT);
}

static void reconnect_after_last_success()
{
    Policy p;
    p.reset_session(1000);
    p.finish_sync(2000, true, 100000);
    p.finish_sync(7000, false, 105000);
    p.finish_sync(12000, false, 110000);
    assert(!p.reconnect_due(16999));
    assert(p.reconnect_due(17000));
    assert(p.maintenance_due(17000) == Policy::RECONNECT);
    assert(!p.motion_allowed(17000, 115000));
}

static void reconnect_success_renews()
{
    Policy p;
    p.reset_session(1000);
    p.finish_sync(15000, true, 100000);
    assert(!p.reconnect_due(16000));
    p.finish_sync(25000, true, 110000);
    p.finish_sync(35000, false, 120000);
    assert(!p.reconnect_due(39999));
    // Even an OK result with no valid native epoch must not renew the lease.
    p.finish_sync(39999, true, 0);
    assert(p.reconnect_due(40000));
}

static void reconnect_rollover()
{
    const uint32_t start = std::numeric_limits<uint32_t>::max() - 1000;
    for (bool initially_synced : {false, true})
    {
        Policy p;
        p.reset_session(start);
        if (initially_synced) p.finish_sync(start, true, 100000);
        assert(!p.reconnect_due(start + 14999));
        assert(p.reconnect_due(start + 15000));
        assert(p.reconnect_due(start + 1)); // Expiry stays latched across wraps.
    }
}

static void reconnect_reset_preserves_stamp()
{
    Policy p;
    p.reset_session(1000);
    p.finish_sync(1000, true, 100000);
    assert(p.accept_stamp(1001, 100001));
    assert(p.maintenance_due(16000) == Policy::RECONNECT);
    p.reset_session(17000);
    assert(!p.reconnect_due(17000));
    assert(!p.motion_allowed(17000, 100002));
    assert(p.maintenance_due(17000) == Policy::SYNC);
    p.finish_sync(17050, true, 99999);
    assert(!p.accept_stamp(17050, 99999));
    assert(!p.accept_stamp(17051, 100001));
    assert(p.accept_stamp(17052, 100002));
    assert(!p.reconnect_due(32049));
    assert(p.reconnect_due(32050));
}

static void options_repeated_lifecycle()
{
    for (int i = 0; i < 10; ++i)
    {
        assert(lifecycle::create_options());
        assert(lifecycle::options_live == 0);
        assert(lifecycle::context_copies == 1);
        assert(!lifecycle::init_options_owned && !lifecycle::init_options.impl);
        lifecycle::destroy_owned_resources();
        assert(lifecycle::options_live == 0 && lifecycle::context_copies == 0);
    }
}

static void options_failed_creation()
{
    for (int stage : {1, 2, 3})
    {
        lifecycle::failure_stage = stage;
        assert(!lifecycle::create_options());
        lifecycle::destroy_owned_resources();
        assert(lifecycle::options_live == 0 && lifecycle::context_copies == 0);
        assert(!lifecycle::init_options_owned && !lifecycle::init_options.impl);
        // Cleanup is safe again after a failed init or a completed release.
        assert(lifecycle::release_init_options());
        lifecycle::failure_stage = 0;
        assert(lifecycle::create_options());
        lifecycle::destroy_owned_resources();
    }
}

static void both_publishers_released()
{
    assert(lifecycle::create_options());
    lifecycle::destroy_owned_resources();
    assert(lifecycle::publisher_fini_calls[0] == 1);
    assert(lifecycle::publisher_fini_calls[1] == 1);
}

static void entity_creation_failures()
{
    for (int stage = 1; stage <= 13; ++stage)
    {
        lifecycle::failure_stage = stage;
        lifecycle::init_calls = 0;
        assert(!lifecycle::create_options());
        assert(lifecycle::last_init_stage == stage);
        assert(lifecycle::init_calls == stage); // No initialization after failure.
        lifecycle::destroy_owned_resources();
        lifecycle::destroy_owned_resources(); // Safe repeated rollback.
        assert(!lifecycle::node.impl && !lifecycle::executor.handles);
        assert(!lifecycle::odom_publisher.impl && !lifecycle::imu_publisher.impl);
        assert(!lifecycle::twist_subscriber.impl && !lifecycle::config_service.impl);
        assert(!lifecycle::timer.impl && !lifecycle::support.clock.initialized);
        assert(!lifecycle::support.context.impl);
        assert(lifecycle::options_live == 0 && lifecycle::context_copies == 0);
        lifecycle::failure_stage = 0;
        assert(lifecycle::create_options());
        assert(lifecycle::executor.added == 3);
        lifecycle::destroy_owned_resources();
    }
}

static void support_partial_failure()
{
    for (bool with_rmw_context : {false, true})
    {
        lifecycle::context_without_rmw_failure = !with_rmw_context;
        lifecycle::partial_context_failure = with_rmw_context;
        const int before = lifecycle::timeout_calls;
        assert(!lifecycle::create_options());
        assert(lifecycle::support.context.impl && !lifecycle::support.clock.initialized);
        lifecycle::destroy_owned_resources();
        assert(!lifecycle::support.context.impl);
        assert(lifecycle::timeout_calls - before == (with_rmw_context ? 1 : 0));
        assert(lifecycle::options_live == 0 && lifecycle::context_copies == 0);
        lifecycle::context_without_rmw_failure = lifecycle::partial_context_failure = false;
        assert(lifecycle::create_options());
        lifecycle::destroy_owned_resources();
    }
}

static void partial_cleanup_stops_motion()
{
    assert(lifecycle::create_options());
    time_sync.finish_sync(0, true, 100000);
    assert(update_command_clock(0, 100000));
    command_valid = true;
    command_received_ms = 0;
    command_targets[0] = command_targets[1] = 12;
    lifecycle::destroy_owned_resources();
    assert(!command_valid && !command_clock_valid);
    sample_motor_targets();
    assert(observed_targets[0] == 0 && observed_targets[1] == 0);
    assert(lifecycle::create_options());
    sample_motor_targets();
    assert(observed_targets[0] == 0); // A new session never replays old velocity.
    lifecycle::destroy_owned_resources();
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    struct Test { const char *name; void (*run)(); };
    const Test tests[] = {
        {"startup", startup}, {"failure_does_not_renew", failure_does_not_renew},
        {"invalid_epoch", invalid_epoch}, {"renewal", renewal},
        {"native_stamps", native_stamps}, {"backward_sync", backward_sync},
        {"reconnect", reconnect}, {"rollover", rollover},
        {"maintenance_budget", maintenance_budget}, {"motor_lease", motor_lease},
        {"connected_sync_heartbeat", connected_sync_heartbeat},
        {"command_watchdog", command_watchdog},
        {"backward_invalidates_motion", backward_invalidates_motion},
        {"display_snapshot", display_snapshot},
        {"reconnect_first_sync_timeout", reconnect_first_sync_timeout},
        {"reconnect_after_last_success", reconnect_after_last_success},
        {"reconnect_success_renews", reconnect_success_renews},
        {"reconnect_rollover", reconnect_rollover},
        {"reconnect_reset_preserves_stamp", reconnect_reset_preserves_stamp},
        {"options_repeated_lifecycle", options_repeated_lifecycle},
        {"options_failed_creation", options_failed_creation},
        {"both_publishers_released", both_publishers_released},
        {"entity_creation_failures", entity_creation_failures},
        {"support_partial_failure", support_partial_failure},
        {"partial_cleanup_stops_motion", partial_cleanup_stops_motion}
    };
    for (const auto &test : tests)
        if (std::strcmp(argv[1], test.name) == 0) { test.run(); return 0; }
    return 2;
}
