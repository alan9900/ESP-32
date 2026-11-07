// Native test harness around the exact microcontroller FrameAssembler source.
// Input and output are binary, and are used only with constructed test data.
#include "frame_assembler.h"
#include <cstdint>
#include <cstdio>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

static bool read_exact(uint8_t *data, size_t length) {
  return fread(data, 1, length, stdin) == length;
}
static uint32_t le32(const uint8_t *p) {
  return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}
static void put_u16(uint16_t value) {
  putchar(value & 0xff);
  putchar((value >> 8) & 0xff);
}
int main() {
  // On Windows stdin/stdout must stay binary or LF and Ctrl-Z would be changed.
#ifdef _WIN32
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  uint8_t count_bytes[2];
  if (!read_exact(count_bytes, sizeof(count_bytes))) return 1;
  const unsigned count = count_bytes[0] | (static_cast<unsigned>(count_bytes[1]) << 8);
  FrameAssembler receiver;
  for (unsigned i = 0; i < count; ++i) {
    uint8_t header[5], frame[255];
    if (!read_exact(header, sizeof(header))) return 2;
    const size_t length = header[4];
    if (!read_exact(frame, length)) return 3;
    receiver.ingest(frame, length, le32(header));
    putchar(receiver.state());
    put_u16(receiver.nextSeq());
  }
  put_u16(static_cast<uint16_t>(receiver.size()));
  if (receiver.size()) fwrite(receiver.data(), 1, receiver.size(), stdout);
  return ferror(stdout) ? 4 : 0;
}
