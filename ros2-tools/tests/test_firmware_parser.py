"""Compile the actual firmware parser methods on the host; no ESP32/flash access."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FirmwareParserTest(unittest.TestCase):
    def test_boundaries_and_uart_recovery(self):
        text = (ROOT / 'fishbot_motion_control_microros/src/fishbot_config.cpp').read_text()
        methods = []
        for name in ('split_str', 'loop_config_uart'):
            start = text.index('int8_t FishBotConfig::' + name)
            end = text.index('\n}', start) + 2
            methods.append(text[start:end])
        source = '''
#include <cstdint>
#include <cstring>
#include <cassert>
#include <string>
constexpr int CONFIG_PARSE_ERROR=-1, CONFIG_PARSE_OK=1, CONFIG_PARSE_NODATA=0;
class FishBotConfig { public:
int8_t split_str(const char*, char[][32]);
int8_t loop_config_uart(int, char[][32]);
};
''' + '\n'.join(methods) + '''
int main() {
    FishBotConfig parser;
    struct { unsigned before=0x12345678; char result[2][32]; unsigned after=0x87654321; } b;
    assert(parser.split_str("$key=value", b.result)==1);
    assert(std::strcmp(b.result[1],"value")==0);
    assert(parser.split_str("$a=b=c", b.result)==-1);
    std::string maximum="$"+std::string(31,'k')+"="+std::string(31,'v');
    assert(parser.split_str(maximum.c_str(), b.result)==1);
    assert(parser.split_str((maximum+"v").c_str(), b.result)==-1);
    for(int i=0;i<1000;i++) parser.loop_config_uart('x', b.result);
    assert(parser.loop_config_uart('\\n', b.result)==-1);
    for(char c:std::string("$a=b")) parser.loop_config_uart(c,b.result);
    assert(parser.loop_config_uart('\\n', b.result)==1);
    assert(b.before==0x12345678 && b.after==0x87654321);
}
'''
        with tempfile.TemporaryDirectory(prefix='fishbot-parser-test-') as directory:
            executable = str(Path(directory) / 'parser-test')
            subprocess.run(['g++', '-x', 'c++', '-std=c++11', '-Wall', '-Wextra',
                            '-fsanitize=undefined,bounds', '-o', executable, '-'],
                           input=source, text=True, check=True, timeout=30)
            subprocess.run([executable], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
