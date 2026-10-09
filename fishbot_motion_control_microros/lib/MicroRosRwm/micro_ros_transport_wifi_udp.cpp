#include <Arduino.h>

#include <micro_ros_platformio.h>

#include <WiFi.h>
#include <WiFiUdp.h>

#include <uxr/client/util/time.h>
#include <uxr/client/profile/transport/custom/custom_transport.h>
#include "micro_ros_transport_wifi_udp.h"
#include "fishbot_xrce_time_filter.h"
extern "C"
{

  static WiFiUDP udp_client;
  static FishbotXrceTimeFilter time_filter;
  // Transport calls and snapshots share the communication task on core 0.
  static uint32_t write_calls = 0;
  static uint64_t write_max_us = 0;
  static uint32_t write_timing_errors = 0;

  void fishbot_udp_time_sync_begin() { time_filter.begin(uxr_nanos()); }
  void fishbot_udp_time_sync_end() { time_filter.end(); }
  void fishbot_udp_write_stats_snapshot(uint32_t *calls, uint64_t *max_us, uint32_t *timing_errors)
  {
    if (calls) *calls = write_calls;
    if (max_us) *max_us = write_max_us;
    if (timing_errors) *timing_errors = write_timing_errors;
    write_calls = 0;
    write_max_us = 0;
    write_timing_errors = 0;
  }

  bool platformio_transport_open_wifi_udp(struct uxrCustomTransport *transport)
  {
    time_filter.reset();
    struct micro_ros_agent_locator *locator = (struct micro_ros_agent_locator *)transport->args;
    return true == udp_client.begin(locator->port);
  }

  bool platformio_transport_close_wifi_udp(struct uxrCustomTransport *transport)
  {
    time_filter.reset();
    udp_client.stop();
    return true;
  }

  size_t platformio_transport_write_wifi_udp(struct uxrCustomTransport *transport, const uint8_t *buf, size_t len, uint8_t *errcode)
  {
    const int64_t write_started_ns = uxr_nanos();
    if (errcode) *errcode = 0;
    struct micro_ros_agent_locator *locator = (struct micro_ros_agent_locator *)transport->args;

    size_t sent = 0;
    if (true == udp_client.beginPacket(locator->address, locator->port))
    {
      sent = udp_client.write(buf, len);
      sent = true == udp_client.endPacket() ? sent : 0;
    }

    udp_client.flush();
    time_filter.sent(buf, len, sent == len, uxr_nanos());

    const int64_t write_finished_ns = uxr_nanos();
    if (write_calls < UINT32_MAX) ++write_calls;
    if (write_started_ns >= 0 && write_finished_ns >= write_started_ns)
    {
      const uint64_t duration_us = static_cast<uint64_t>(write_finished_ns - write_started_ns) / 1000;
      if (duration_us > write_max_us) write_max_us = duration_us;
    }
    else if (write_timing_errors < UINT32_MAX)
    {
      ++write_timing_errors;
    }

    return sent;
  }

  size_t platformio_transport_read_wifi_udp(struct uxrCustomTransport *transport, uint8_t *buf, size_t len, int timeout, uint8_t *errcode)
  {
    (void)transport;
    if (errcode) *errcode = 0;
    const int64_t start_ns = uxr_nanos();
    const int64_t timeout_ns = timeout > 0 ? static_cast<int64_t>(timeout) * 1000000 : 0;
    do
    {
      const int packet_size = udp_client.parsePacket();
      if (packet_size > 0)
      {
        int received = 0;
        if (static_cast<size_t>(packet_size) <= len) received = udp_client.read(buf, len);
        // Discard the entire current datagram, including any truncated remainder.
        udp_client.flush();
        if (received == packet_size && time_filter.receive(buf, received, uxr_nanos()))
          return static_cast<size_t>(received);
      }
      else if (udp_client.available())
      {
        // Arduino parsePacket returns zero while an old rx buffer still exists.
        udp_client.flush();
      }
      // timeout == 0 still performs exactly one nonblocking parse attempt.
      if (uxr_nanos() - start_ns >= timeout_ns) break;
      delay(1);
    } while (true);
    return 0;
  }
}
