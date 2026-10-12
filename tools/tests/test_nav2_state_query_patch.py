"""Compile the actual patched manager method against deterministic service doubles.

Run through fishbot_nav2_state_query_overlay.sh test after preparing the pinned source.
No ROS nodes or network calls are made. DDS fault injection remains a separate check.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HARNESS = r'''
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

static bool context_ok = true;
static std::vector<std::string> logs;
template<class... Args> void log(int, const char * format, Args... args) {
  char buffer[2048];
  std::snprintf(buffer, sizeof(buffer), format, args...);
  logs.emplace_back(buffer);
}
#define RCLCPP_ERROR(...) log(__VA_ARGS__)
#define RCLCPP_WARN(...) log(__VA_ARGS__)
#define RCLCPP_INFO(...) log(__VA_ARGS__)
namespace rclcpp { bool ok() { return context_ok; } }
struct Transition {
  static constexpr std::uint8_t TRANSITION_ACTIVATE = 3;
  static constexpr std::uint8_t TRANSITION_DEACTIVATE = 4;
};
struct Client {
  std::string mode;
  unsigned int changes = 0;
  unsigned int queries = 0;
  bool change_state(std::uint8_t) {
    ++changes;
    if (mode == "change_false") { return false; }
    if (mode == "change_throw") { throw std::runtime_error("mutation failed"); }
    return true;
  }
  std::uint8_t get_state() {
    ++queries;
    if (mode == "shutdown") {
      context_ok = false;
      throw std::runtime_error("interrupted");
    }
    if (mode == "query_logic_error") { throw std::logic_error("unexpected exception"); }
    if (mode == "query_timeout" ||
      ((mode == "retry_correct" || mode == "retry_wrong") && queries == 1))
    {
      throw std::runtime_error("get_state async_send_request failed");
    }
    return mode == "wrong" || mode == "retry_wrong" ? 99 : 2;
  }
};
class LifecycleManager {
public:
  std::map<std::string, std::shared_ptr<Client>> node_map_;
  std::map<std::uint8_t, std::uint8_t> transition_state_map_{{1, 2}};
  std::map<std::uint8_t, std::string> transition_label_map_{{1, "Configuring "}};
  std::map<std::string, int> bond_map_;
  unsigned int bond_calls = 0;
  int get_logger() { return 0; }
  void message(const std::string &) {}
  bool createBondConnection(const std::string &) { ++bond_calls; return true; }
  bool changeStateForNode(const std::string &, std::uint8_t);
};

// The function below is extracted verbatim from the prepared upstream source.
__ACTUAL_METHOD__

int main(int argc, char ** argv) {
  if (argc != 2) { return 2; }
  const std::string mode = argv[1];
  auto client = std::make_shared<Client>();
  client->mode = mode;
  LifecycleManager manager;
  manager.node_map_["fixture"] = client;
  bool result = false;
  std::string exception;
  try { result = manager.changeStateForNode("fixture", 1); }
  catch (const std::exception & error) { exception = error.what(); }
  std::printf("changes=%u queries=%u result=%s exception=%s\n",
    client->changes, client->queries, result ? "true" : "false", exception.c_str());
  for (const auto & item : logs) { std::puts(item.c_str()); }
  return 0;
}
'''


class StateQueryPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_path = os.environ.get('FISHBOT_NAV2_PATCHED_SOURCE')
        if not source_path:
            raise RuntimeError('Run tools/fishbot_nav2_state_query_overlay.sh test; pinned source is required.')
        source = Path(source_path).read_text()
        begin = source.index('bool\nLifecycleManager::changeStateForNode(')
        end = source.index('bool\nLifecycleManager::changeStateForAllNodes(', begin)
        method = source[begin:end]
        cls.temporary = tempfile.TemporaryDirectory(prefix='fishbot-state-query-test-')
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        harness = directory / 'harness.cpp'
        cls.executable = directory / 'harness'
        harness.write_text(HARNESS.replace('__ACTUAL_METHOD__', method))
        subprocess.run(['/usr/bin/g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        str(harness), '-o', str(cls.executable)],
                       check=True, capture_output=True, text=True, timeout=30)

    def run_mode(self, mode):
        return subprocess.run([str(self.executable), mode], check=True,
                              capture_output=True, text=True, timeout=3).stdout

    def test_initial_correct_state_uses_one_query(self):
        output = self.run_mode('correct')
        self.assertIn('changes=1 queries=1 result=true exception=\n', output)
        self.assertIn('attempt=1/2 elapsed_ms=', output)
        self.assertNotIn('attempt=2/2', output)

    def test_query_timeout_then_correct_does_not_repeat_transition(self):
        output = self.run_mode('retry_correct')
        self.assertIn('changes=1 queries=2 result=true exception=\n', output)
        self.assertIn('retry=true', output)
        self.assertIn('attempt=2/2 elapsed_ms=', output)

    def test_wrong_state_does_not_retry(self):
        output = self.run_mode('wrong')
        self.assertIn('changes=1 queries=1 result=false exception=\n', output)
        self.assertIn('state=99 expected=2', output)
        self.assertNotIn('attempt=2/2', output)

    def test_second_query_wrong_state_fails(self):
        output = self.run_mode('retry_wrong')
        self.assertIn('changes=1 queries=2 result=false exception=\n', output)
        self.assertIn('state=99 expected=2', output)

    def test_persistent_query_timeout_is_bounded_and_preserved(self):
        output = self.run_mode('query_timeout')
        self.assertIn('changes=1 queries=2 result=false exception=get_state async_send_request failed', output)
        self.assertIn('retry=false', output)
        self.assertNotIn('attempt=3', output)

    def test_failed_mutation_never_queries(self):
        output = self.run_mode('change_false')
        self.assertIn('changes=1 queries=0 result=false exception=\n', output)
        self.assertNotIn('State confirmation', output)

    def test_mutation_exception_is_preserved_without_queries(self):
        output = self.run_mode('change_throw')
        self.assertIn('changes=1 queries=0 result=false exception=mutation failed', output)
        self.assertNotIn('State confirmation', output)

    def test_shutdown_does_not_retry(self):
        output = self.run_mode('shutdown')
        self.assertIn('changes=1 queries=1 result=false exception=interrupted', output)
        self.assertIn('retry=false', output)
        self.assertNotIn('attempt=2/2', output)

    def test_non_runtime_exception_is_not_swallowed(self):
        output = self.run_mode('query_logic_error')
        self.assertIn('changes=1 queries=1 result=false exception=unexpected exception', output)
        self.assertNotIn('retry=', output)


if __name__ == '__main__':
    unittest.main()
