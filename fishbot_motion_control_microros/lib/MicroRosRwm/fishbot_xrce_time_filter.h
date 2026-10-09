#ifndef FISHBOT_XRCE_TIME_FILTER_H
#define FISHBOT_XRCE_TIME_FILTER_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "fishbot_time_sync_policy.h"

// XRCE 2.4.2 wire layout, as serialized by xrce_header.c, xrce_subheader.c,
// and xrce_types.c. No SDK state or offset is changed by this filter.
class FishbotXrceTimeFilter
{
public:
    void reset() { attempt_ = false; pending_ = false; }
    void begin(int64_t now_ns)
    {
        reset();
        attempt_ = now_ns >= 0;
        attempt_start_ns_ = now_ns;
    }
    void end() { reset(); }

    void sent(const uint8_t *data, size_t size, bool complete, int64_t now_ns)
    {
        Parsed parsed;
        if (!parse(data, size, parsed) || !parsed.requests) return;
        pending_ = false;
        int64_t origin;
        if (!complete || !attempt_ || data[1] != 0 || parsed.requests != 1 || parsed.replies ||
            parsed.request_size != 8 || (parsed.request_flags & ~1u) ||
            !time_value(parsed.request, parsed.request_flags, origin) ||
            !within(now_ns, attempt_start_ns_) || !within(now_ns, origin) ||
            origin < attempt_start_ns_) return;
        origin_ns_ = origin;
        session_id_ = data[0];
        if (session_id_ < 0x80) memcpy(client_key_, data + 4, 4);
        pending_ = true;
    }

    bool receive(const uint8_t *data, size_t size, int64_t now_ns)
    {
        Parsed parsed;
        if (!parse(data, size, parsed, true)) return false;
        if (!parsed.replies) return true; // Ordinary datagrams remain byte-identical.
        int64_t t0, t1, t2;
        if (!attempt_ || !pending_ || parsed.replies != 1 || parsed.reply_size != 24 ||
            (parsed.reply_flags & ~1u) || data[0] != session_id_ ||
            (session_id_ < 0x80 && memcmp(client_key_, data + 4, 4) != 0) ||
            !time_value(parsed.reply, parsed.reply_flags, t2) ||
            !time_value(parsed.reply + 8, parsed.reply_flags, t1) ||
            !time_value(parsed.reply + 16, parsed.reply_flags, t0) ||
            t0 != origin_ns_ || !within(now_ns, attempt_start_ns_) ||
            !within(now_ns, t0) || t2 < t1) return false;
        const int64_t elapsed_ns = now_ns - t0;
        const int64_t server_ns = t2 - t1;
        if (server_ns > elapsed_ns) return false;
        const int64_t round_trip_ns = elapsed_ns - server_ns;
        if (round_trip_ns > budget_ns()) return false;
        pending_ = false; // One reply per request, including copies in later spin calls.
        return true;
    }

private:
    struct Parsed
    {
        size_t requests = 0, replies = 0;
        const uint8_t *request = nullptr, *reply = nullptr;
        size_t request_size = 0, reply_size = 0;
        uint8_t request_flags = 0, reply_flags = 0;
    };

    static int64_t budget_ns()
    {
        return static_cast<int64_t>(FishbotTimeSyncPolicy::sync_timeout_ms) * 1000000;
    }
    static bool within(int64_t now_ns, int64_t start_ns)
    {
        return start_ns >= 0 && now_ns >= start_ns && now_ns - start_ns <= budget_ns();
    }
    static uint32_t u32(const uint8_t *p, bool little)
    {
        return little ? static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
            (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24) :
            (static_cast<uint32_t>(p[0]) << 24) | (static_cast<uint32_t>(p[1]) << 16) |
            (static_cast<uint32_t>(p[2]) << 8) | static_cast<uint32_t>(p[3]);
    }
    static bool time_value(const uint8_t *p, uint8_t flags, int64_t &value)
    {
        const uint32_t seconds = u32(p, flags & 1u);
        const uint32_t nanos = u32(p + 4, flags & 1u);
        if (seconds > INT32_MAX || nanos >= 1000000000u) return false;
        value = static_cast<int64_t>(seconds) * 1000000000 + nanos;
        return true;
    }
    static bool supported_incoming(uint8_t id, uint8_t flags, const uint8_t *payload,
                                   size_t length, uint8_t stream)
    {
        // Client 2.4.2 does NOT skip unknown submessages by their length. Several
        // defined formats are also TODOs. Reject those instead of letting their
        // payload be reinterpreted as another (possibly timestamp) submessage.
        switch (id)
        {
        case 2: return length == 8; // GET_INFO
        case 4: return stream == 0 && length == 11 && payload[10] == 0; // STATUS_AGENT, no properties
        case 5: return length == 6; // STATUS
        case 6: // INFO: simple pong or the captured Agent config + activity pong.
            return (length == 8 && payload[6] == 0 && payload[7] == 0) ||
                (length == 12 && payload[6] == 0 && payload[7] == 1 && payload[8] == 0x0d) ||
                (length == 28 && payload[6] == 1 && payload[7] == 0x0d &&
                 payload[16] == 0 && payload[17] == 1 && payload[18] == 0x0d &&
                 payload[22] == 0 && payload[23] == 0 &&
                 payload[24] == 0 && payload[25] == 0 && payload[26] == 0 && payload[27] == 0);
            // For INFO28, Client 2.4.2 consumes 22 bytes, aligns to 24, and
            // reads the empty address count as a harmless zero-length header.
            // A nonzero tail could be interpreted as another submessage.
        case 9: // DATA: only FORMAT_DATA advances by the declared payload size.
            return length >= 4 && (flags & 0x0e) == 0 && (payload[3] & 0x0f) != 7;
        case 10: case 11: return length == 5; // ACKNACK / HEARTBEAT
        case 15: return stream == 0 && length == 24; // No reliable deferred timestamps.
        default: return false;
        }
        // Fragmented inbound data is intentionally unsupported: the SDK can
        // reassemble and process a hidden timestamp after this receive window.
    }
    static bool parse(const uint8_t *data, size_t size, Parsed &out, bool incoming = false)
    {
        if (!data || size < 4) return false;
        size_t offset = data[0] < 0x80 ? 8 : 4;
        if (size < offset) return false;
        while (offset < size)
        {
            const size_t padding = (4 - offset % 4) % 4;
            // The final submessage need not carry trailing alignment bytes.
            if (size - offset <= padding) return true;
            offset += padding;
            if (size - offset < 4) return false;
            const uint8_t id = data[offset], flags = data[offset + 1];
            // XRCE submessage length is ALWAYS little endian, unlike its payload.
            const size_t length = data[offset + 2] | (static_cast<size_t>(data[offset + 3]) << 8);
            offset += 4;
            if (length > size - offset) return false;
            if (incoming && !supported_incoming(id, flags, data + offset, length, data[1])) return false;
            if (id == 14)
            {
                ++out.requests;
                out.request = data + offset; out.request_size = length; out.request_flags = flags;
            }
            else if (id == 15)
            {
                ++out.replies;
                out.reply = data + offset; out.reply_size = length; out.reply_flags = flags;
            }
            offset += length;
        }
        return true;
    }

    bool attempt_ = false, pending_ = false;
    int64_t attempt_start_ns_ = 0, origin_ns_ = 0;
    uint8_t session_id_ = 0, client_key_[4] = {0, 0, 0, 0};
};

#endif
