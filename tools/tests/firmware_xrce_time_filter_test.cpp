#include <algorithm>
#include <cassert>
#include <cstring>
#include <deque>
#include <string>
#include <vector>
#include "fishbot_xrce_time_filter.h"

// The real transport implementation is compiled with only UDP/Arduino replaced.
static int64_t fake_ns = INT64_C(10000000000);
static int64_t uxr_nanos() { return fake_ns; }
static void delay(int ms) { fake_ns += static_cast<int64_t>(ms) * 1000000; }
struct micro_ros_agent_locator { int address = 1, port = 8888; } locator;
struct uxrCustomTransport { void *args = &locator; } transport;
class WiFiUDP
{
public:
    std::deque<std::vector<uint8_t>> packets;
    std::vector<uint8_t> current;
    size_t read_limit = SIZE_MAX, write_limit = SIZE_MAX;
    bool send_ok = true;
    int parse_calls = 0;
    bool begin(int) { return true; }
    void stop() { packets.clear(); current.clear(); }
    bool beginPacket(int, int) { return true; }
    size_t write(const uint8_t *, size_t size) { return std::min(size, write_limit); }
    bool endPacket() { return send_ok; }
    void flush() { current.clear(); }
    int available() { return static_cast<int>(current.size()); }
    int parsePacket()
    {
        ++parse_calls;
        if (!current.empty() || packets.empty()) return 0;
        current = packets.front(); packets.pop_front();
        return static_cast<int>(current.size());
    }
    int read(uint8_t *out, size_t size)
    {
        const size_t count = std::min(std::min(size, current.size()), read_limit);
        std::copy(current.begin(), current.begin() + count, out);
        current.erase(current.begin(), current.begin() + count);
        return static_cast<int>(count);
    }
};
#include "udp_transport_under_test.h"

using Bytes = std::vector<uint8_t>;
static constexpr int64_t origin = INT64_C(10000000000);
static constexpr int64_t server = INT64_C(1791477000000000000);
static void u32(Bytes &out, uint32_t value, bool little)
{
    for (int i = 0; i < 4; ++i) out.push_back(static_cast<uint8_t>(value >> (8 * (little ? i : 3 - i))));
}
static void time_value(Bytes &out, int64_t value, bool little)
{
    u32(out, static_cast<uint32_t>(value / 1000000000), little);
    u32(out, static_cast<uint32_t>(value % 1000000000), little);
}
static Bytes header(uint8_t session = 0x81)
{
    Bytes out{session, 0, 0x34, 0x12};
    if (session < 0x80) out.insert(out.end(), {1, 2, 3, 4});
    return out;
}
static void submessage(Bytes &out, uint8_t id, bool little, const Bytes &payload)
{
    while (out.size() % 4) out.push_back(0);
    out.insert(out.end(), {id, static_cast<uint8_t>(little), static_cast<uint8_t>(payload.size()),
                          static_cast<uint8_t>(payload.size() >> 8)});
    out.insert(out.end(), payload.begin(), payload.end());
}
static Bytes request(int64_t t0 = origin, bool little = true, uint8_t session = 0x81)
{
    Bytes out = header(session), payload;
    time_value(payload, t0, little); submessage(out, 14, little, payload); return out;
}
static Bytes reply(int64_t t0 = origin, int64_t t1 = server, int64_t t2 = server + 1000000,
                   bool little = true, uint8_t session = 0x81)
{
    Bytes out = header(session), payload;
    time_value(payload, t2, little); time_value(payload, t1, little); time_value(payload, t0, little);
    submessage(out, 15, little, payload); return out;
}
static void arm(FishbotXrceTimeFilter &filter, bool little = true, uint8_t session = 0x81)
{
    filter.begin(origin);
    const Bytes packet = request(origin, little, session);
    filter.sent(packet.data(), packet.size(), true, origin + 1000);
}

static void layouts()
{
    for (bool little : {false, true}) for (uint8_t session : {uint8_t(0x81), uint8_t(0x01)})
    {
        FishbotXrceTimeFilter filter; arm(filter, little, session);
        Bytes packet = header(session), part = reply(origin, server, server + 1000000, little, session);
        submessage(packet, 11, little, {1, 2, 3, 4, 5}); // 3 alignment bytes follow.
        while (packet.size() % 4) packet.push_back(0);
        packet.insert(packet.end(), part.begin() + (session < 0x80 ? 8 : 4), part.end());
        submessage(packet, 11, little, {1, 2, 3, 4, 5}); // No final padding required.
        assert(filter.receive(packet.data(), packet.size(), origin + 3000000));
    }
}
static void mismatches()
{
    FishbotXrceTimeFilter filter; arm(filter);
    for (const Bytes &packet : {reply(origin - 1), reply(origin + 1),
                              reply(origin, server, server + 1000000, true, 0x82)})
        assert(!filter.receive(packet.data(), packet.size(), origin + 3000000));
    Bytes valid = reply();
    assert(filter.receive(valid.data(), valid.size(), origin + 3000000));
    assert(!filter.receive(valid.data(), valid.size(), origin + 4000000));
    arm(filter, true, 0x01);
    Bytes wrong_key = reply(origin, server, server + 1000000, true, 0x01);
    wrong_key[4] ^= 1;
    assert(!filter.receive(wrong_key.data(), wrong_key.size(), origin + 3000000));
}
static void time_bounds()
{
    Bytes valid = reply();
    FishbotXrceTimeFilter filter; arm(filter);
    assert(!filter.receive(valid.data(), valid.size(), origin - 1));
    assert(!filter.receive(valid.data(), valid.size(), origin + 50000001));
    arm(filter);
    for (const Bytes &packet : {reply(origin, server, server - 1),
                              reply(origin, server, server + 4000000)})
        assert(!filter.receive(packet.data(), packet.size(), origin + 3000000));
    assert(filter.receive(valid.data(), valid.size(), origin + 50000000));
    arm(filter);
    Bytes bad_nanos = valid;
    bad_nanos[12] = 0; bad_nanos[13] = 0xca; bad_nanos[14] = 0x9a; bad_nanos[15] = 0x3b;
    assert(!filter.receive(bad_nanos.data(), bad_nanos.size(), origin + 3000000));
}
static void windows_and_send()
{
    FishbotXrceTimeFilter filter;
    Bytes sent = request(), received = reply();
    filter.sent(sent.data(), sent.size(), true, origin);
    assert(!filter.receive(received.data(), received.size(), origin + 3000000));
    filter.begin(origin); filter.sent(sent.data(), sent.size(), false, origin);
    assert(!filter.receive(received.data(), received.size(), origin + 3000000));
    arm(filter); filter.end();
    assert(!filter.receive(received.data(), received.size(), origin + 3000000));
    arm(filter); filter.reset(); filter.begin(origin + 1000000);
    assert(!filter.receive(received.data(), received.size(), origin + 3000000));
    filter.sent(sent.data(), sent.size(), true, origin + 2000000); // t0 predates attempt.
    assert(!filter.receive(received.data(), received.size(), origin + 3000000));
}
static void mixed_atomic_rejection()
{
    FishbotXrceTimeFilter filter; arm(filter);
    Bytes valid = reply(), duplicate = valid;
    duplicate.insert(duplicate.end(), valid.begin() + 4, valid.end());
    assert(!filter.receive(duplicate.data(), duplicate.size(), origin + 3000000));
    Bytes malformed = valid; malformed.push_back(15);
    assert(!filter.receive(malformed.data(), malformed.size(), origin + 3000000));
    Bytes mixed = header(); submessage(mixed, 11, true, {1, 2, 3, 4, 5});
    while (mixed.size() % 4) mixed.push_back(0);
    Bytes bad = reply(origin - 1); mixed.insert(mixed.end(), bad.begin() + 4, bad.end());
    assert(!filter.receive(mixed.data(), mixed.size(), origin + 3000000));
    // None of the discarded packets consumes the real pending response.
    assert(filter.receive(valid.data(), valid.size(), origin + 4000000));
}
static void truncation_and_ordinary()
{
    Bytes valid = reply();
    for (size_t size = 5; size < valid.size(); ++size)
    {
        FishbotXrceTimeFilter filter; arm(filter);
        assert(!filter.receive(valid.data(), size, origin + 3000000));
    }
    FishbotXrceTimeFilter filter;
    Bytes ordinary = header(); submessage(ordinary, 11, true, {1, 2, 3, 4, 5});
    const Bytes original = ordinary;
    assert(filter.receive(ordinary.data(), ordinary.size(), origin));
    assert(ordinary == original);
    Bytes oversized = valid; oversized[6] = 0xff; oversized[7] = 0xff;
    arm(filter); assert(!filter.receive(oversized.data(), oversized.size(), origin + 3000000));
}
static Bytes ordinary()
{
    Bytes out = header(); submessage(out, 11, true, {1, 2, 3, 4, 5}); return out;
}
static void transport_zero_timeout()
{
    uint8_t output[128], error = 99;
    udp_client.packets.push_back(ordinary());
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == ordinary().size());
    assert(udp_client.parse_calls == 1 && error == 0);
    const Bytes expected = ordinary();
    assert(std::equal(expected.begin(), expected.end(), output));
}
static void transport_partial_and_oversize()
{
    uint8_t output[128], error = 0;
    udp_client.read_limit = 3;
    udp_client.packets.push_back(ordinary());
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == 0);
    assert(udp_client.available() == 0);
    udp_client.read_limit = SIZE_MAX;
    udp_client.packets.push_back(ordinary());
    assert(platformio_transport_read_wifi_udp(&transport, output, 3, 0, &error) == 0);
    assert(udp_client.available() == 0);
    udp_client.packets.push_back(ordinary());
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == ordinary().size());
}
static void transport_drop_then_continue()
{
    uint8_t output[128], error = 0;
    udp_client.packets.push_back(reply()); // No attempt: stale even with matching-looking origin.
    udp_client.packets.push_back(ordinary());
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 10, &error) == ordinary().size());
    assert(udp_client.parse_calls == 2);
}
static void transport_reopen_and_failed_send()
{
    uint8_t output[128], error = 0;
    Bytes sent = request();
    platformio_transport_open_wifi_udp(&transport);
    fishbot_udp_time_sync_begin();
    udp_client.send_ok = false;
    assert(platformio_transport_write_wifi_udp(&transport, sent.data(), sent.size(), &error) == 0);
    udp_client.packets.push_back(reply()); fake_ns += 3000000;
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == 0);
    fake_ns = origin; fishbot_udp_time_sync_begin(); udp_client.send_ok = true;
    platformio_transport_write_wifi_udp(&transport, sent.data(), sent.size(), &error);
    platformio_transport_close_wifi_udp(&transport);
    platformio_transport_open_wifi_udp(&transport);
    udp_client.packets.push_back(reply()); fake_ns += 3000000;
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == 0);
}

static void hidden_replies_are_rejected()
{
    FishbotXrceTimeFilter filter; arm(filter);
    Bytes hidden = reply(origin - 1), inner(hidden.begin() + 4, hidden.end());
    // Unknown/default and deferred fragment paths must not hide a timestamp.
    for (uint8_t id : {0, 1, 3, 7, 8, 12, 13, 14, 16, 255})
    {
        Bytes packet = header(); submessage(packet, id, true, inner);
        assert(!filter.receive(packet.data(), packet.size(), origin + 3000000));
    }
    // SDK consumes fixed fields, not a forged larger declared payload length.
    for (uint8_t id : {5, 10, 11})
    {
        Bytes payload(8, 0); payload.insert(payload.end(), inner.begin(), inner.end());
        Bytes packet = header(); submessage(packet, id, true, payload);
        assert(!filter.receive(packet.data(), packet.size(), origin + 3000000));
    }
    Bytes payload{0, 0, 0, 6}; payload.insert(payload.end(), inner.begin(), inner.end());
    Bytes packet = header(); submessage(packet, 9, true, payload);
    packet[5] |= 2; // FORMAT_SAMPLE is an unimplemented SDK branch.
    assert(!filter.receive(packet.data(), packet.size(), origin + 3000000));
    packet[5] = 1; packet[11] = 7; // REQUESTER has a double-advance SDK path.
    assert(!filter.receive(packet.data(), packet.size(), origin + 3000000));
    Bytes valid = reply();
    assert(filter.receive(valid.data(), valid.size(), origin + 4000000));
}

static void ordinary_profile()
{
    FishbotXrceTimeFilter filter;
    Bytes agent(11, 0), status(6, 0), get_info(8, 0), info(8, 0), pong(12, 0);
    pong[7] = 1; pong[8] = 0x0d; pong[10] = 1;
    Bytes data{0, 0, 0, 6};
    Bytes looks_like_time = reply();
    data.insert(data.end(), looks_like_time.begin(), looks_like_time.end());
    struct Ordinary { uint8_t id; Bytes payload; };
    for (const auto &item : std::vector<Ordinary>{{4, agent}, {5, status}, {2, get_info},
             {6, info}, {6, pong}, {9, data}, {10, Bytes(5, 0)}, {11, Bytes(5, 0)}})
    {
        Bytes packet = header(); submessage(packet, item.id, true, item.payload);
        Bytes original = packet;
        assert(filter.receive(packet.data(), packet.size(), origin));
        assert(packet == original);
    }
    Bytes config_variant = header(); pong[6] = 1; submessage(config_variant, 6, true, pong);
    assert(!filter.receive(config_variant.data(), config_variant.size(), origin));
    Bytes deferred = reply(); deferred[1] = 0x80;
    arm(filter); assert(!filter.receive(deferred.data(), deferred.size(), origin + 3000000));
}

static void captured_agent_info28()
{
    // Public protocol bytes captured from the actual Agent pong on 2026-10-09.
    // session=128, stream=0, INFO length=28, little-endian availability=1.
    const Bytes captured_payload{0, 10, 255, 253, 0, 0, 1, 13, 88, 82, 67, 69,
                                1, 0, 1, 15, 0, 1, 13, 0, 1, 0, 0, 0, 0, 0, 0, 0};
    FishbotXrceTimeFilter filter;
    for (bool little : {false, true})
    {
        Bytes payload = captured_payload;
        payload[20] = little ? 1 : 0;
        payload[21] = little ? 0 : 1;
        Bytes packet = header(0x80); submessage(packet, 6, little, payload);
        const Bytes original = packet;
        assert(filter.receive(packet.data(), packet.size(), origin));
        assert(packet == original);
        // Neither endian form may smuggle a second submessage through the
        // SDK's unconsumed empty-address tail.
        for (size_t index = 22; index < 28; ++index)
        {
            Bytes bad = payload; bad[index] = 15;
            Bytes hidden = header(0x80); submessage(hidden, 6, little, bad);
            assert(!filter.receive(hidden.data(), hidden.size(), origin));
        }
        for (size_t index : {size_t(6), size_t(7), size_t(16), size_t(17), size_t(18)})
        {
            Bytes bad = payload; bad[index] ^= 1;
            Bytes unsupported = header(0x80); submessage(unsupported, 6, little, bad);
            assert(!filter.receive(unsupported.data(), unsupported.size(), origin));
        }
    }
    // A pong must not consume a pending clock reply when both share a datagram.
    arm(filter);
    Bytes mixed = header(); submessage(mixed, 6, true, captured_payload);
    Bytes timestamp = reply(); mixed.insert(mixed.end(), timestamp.begin() + 4, timestamp.end());
    assert(filter.receive(mixed.data(), mixed.size(), origin + 3000000));
    assert(!filter.receive(timestamp.data(), timestamp.size(), origin + 4000000));
}

static void transport_success_and_partial_send()
{
    uint8_t output[128], error = 0;
    Bytes sent = request();
    fishbot_udp_time_sync_begin(); udp_client.write_limit = 3;
    assert(platformio_transport_write_wifi_udp(&transport, sent.data(), sent.size(), &error) == 3);
    udp_client.packets.push_back(reply()); fake_ns += 3000000;
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == 0);
    fake_ns = origin; fishbot_udp_time_sync_begin(); udp_client.write_limit = SIZE_MAX;
    assert(platformio_transport_write_wifi_udp(&transport, sent.data(), sent.size(), &error) == sent.size());
    udp_client.packets.push_back(reply()); fake_ns += 3000000;
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == reply().size());
    udp_client.packets.push_back(reply());
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == 0);
    fake_ns = origin; fishbot_udp_time_sync_begin();
    platformio_transport_write_wifi_udp(&transport, sent.data(), sent.size(), &error);
    fishbot_udp_time_sync_end(); udp_client.packets.push_back(reply()); fake_ns += 3000000;
    assert(platformio_transport_read_wifi_udp(&transport, output, sizeof(output), 0, &error) == 0);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    struct Test { const char *name; void (*run)(); };
    const Test tests[] = {{"layouts", layouts}, {"mismatches", mismatches}, {"time_bounds", time_bounds},
        {"windows_and_send", windows_and_send}, {"mixed_atomic_rejection", mixed_atomic_rejection},
        {"truncation_and_ordinary", truncation_and_ordinary}, {"transport_zero_timeout", transport_zero_timeout},
        {"transport_partial_and_oversize", transport_partial_and_oversize},
        {"transport_drop_then_continue", transport_drop_then_continue},
        {"transport_reopen_and_failed_send", transport_reopen_and_failed_send},
        {"hidden_replies_are_rejected", hidden_replies_are_rejected},
        {"ordinary_profile", ordinary_profile},
        {"captured_agent_info28", captured_agent_info28},
        {"transport_success_and_partial_send", transport_success_and_partial_send}};
    for (const auto &test : tests) if (test.name == std::string(argv[1])) { test.run(); return 0; }
    return 2;
}
