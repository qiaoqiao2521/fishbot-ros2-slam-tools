#ifndef FISHBOT_TIME_SYNC_POLICY_H
#define FISHBOT_TIME_SYNC_POLICY_H

#include <stdint.h>

// Owned by the transport task. No ROS, Arduino, or wall-clock adjustment here.
class FishbotTimeSyncPolicy
{
public:
    static constexpr uint32_t sync_period_ms = 5000;
    static constexpr uint32_t sync_timeout_ms = 50;
    static constexpr uint32_t sync_max_age_ms = 15000;
    // Only WAITING_AGENT uses a separate discovery ping.
    static constexpr uint32_t ping_timeout_ms = 100;

    enum Maintenance { NONE, SYNC, RECONNECT };

    Maintenance maintenance_due(uint32_t now_ms)
    {
        if (reconnect_due(now_ms)) return RECONNECT;
        if (sync_due(now_ms)) return SYNC;
        return NONE;
    }

    bool sync_due(uint32_t now_ms) const
    {
        return !attempted_ || elapsed(now_ms, last_attempt_ms_) >= sync_period_ms;
    }

    void begin_sync(uint32_t now_ms)
    {
        attempted_ = true;
        last_attempt_ms_ = now_ms;
    }

    // A failed call must not renew the lease even if the RMW synchronized flag
    // remains true from an earlier exchange.
    void finish_sync(uint32_t now_ms, bool succeeded, int64_t epoch_ms)
    {
        if (succeeded && epoch_ms > 0)
        {
            has_sync_ = true;
            has_sync_in_session_ = true;
            last_sync_ms_ = now_ms;
            sync_reference_ms_ = now_ms;
            reconnect_required_ = false;
        }
    }

    bool reconnect_due(uint32_t now_ms)
    {
        // Only successful session synchronization renews the heartbeat lease.
        // Count from session creation until the first successful synchronization.
        if (elapsed(now_ms, sync_reference_ms_) >= sync_max_age_ms)
            reconnect_required_ = true;
        return reconnect_required_;
    }

    bool fresh(uint32_t now_ms)
    {
        if (has_sync_ && elapsed(now_ms, last_sync_ms_) >= sync_max_age_ms)
            has_sync_ = false; // Expiration cannot revive at the next millis wrap.
        return has_sync_;
    }

    bool motion_allowed(uint32_t now_ms, int64_t epoch_ms)
    {
        // Equality can occur when Twist and the sensor timer run in one ms.
        return fresh(now_ms) && epoch_ms > 0 && epoch_ms >= last_stamp_ms_;
    }

    bool accept_stamp(uint32_t now_ms, int64_t epoch_ms)
    {
        if (!fresh(now_ms) || epoch_ms <= 0 || epoch_ms <= last_stamp_ms_)
            return false;
        last_stamp_ms_ = epoch_ms;
        return true;
    }

    void reset_session(uint32_t now_ms)
    {
        attempted_ = false;
        has_sync_ = false;
        has_sync_in_session_ = false;
        sync_reference_ms_ = now_ms;
        reconnect_required_ = false;
        // Preserve the published watermark across reconnects. Never clamp or
        // re-stamp data if the new session's native epoch is behind it.
    }

    uint32_t last_sync_ms() const { return last_sync_ms_; }
    int64_t last_success_age_ms(uint32_t now_ms) const
    {
        return has_sync_in_session_ ? static_cast<int64_t>(elapsed(now_ms, last_sync_ms_)) : -1;
    }

    static uint32_t elapsed(uint32_t now_ms, uint32_t then_ms)
    {
        return static_cast<uint32_t>(now_ms - then_ms);
    }

private:
    bool attempted_ = false;
    bool has_sync_ = false;
    bool has_sync_in_session_ = false;
    bool reconnect_required_ = false;
    uint32_t last_attempt_ms_ = 0;
    uint32_t last_sync_ms_ = 0;
    uint32_t sync_reference_ms_ = 0;
    int64_t last_stamp_ms_ = 0;
};

#endif
