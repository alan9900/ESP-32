// Host-side unit test for the real receiver implementation. It contains only
// synthetic bytes; compile with frame_assembler.cpp using a native C++ compiler.
#include "../src/frame_assembler.h"
#include <cassert>
#include <cstdint>
#include <cstring>

int main() {
  FrameAssembler rx;
  const uint8_t begin[] = {1, 9, 0, 0x26, 0x39, 0xf4, 0xcb};  // CRC32 of 123456789.
  const uint8_t data[] = {2, 0, 0, '1','2','3','4','5','6','7','8','9'};
  const uint8_t end[] = {3};
  rx.ingest(begin, sizeof(begin), 10);
  assert(rx.state() == 1 && rx.nextSeq() == 0);
  rx.ingest(data, sizeof(data), 20);
  assert(rx.state() == 1 && rx.nextSeq() == 1 && rx.size() == 9);
  rx.ingest(end, sizeof(end), 30);
  assert(rx.state() == 2 && std::memcmp(rx.data(), "123456789", 9) == 0);

  rx.reset();
  const uint8_t bad_sequence[] = {2, 1, 0, '1'};
  rx.ingest(begin, sizeof(begin), 40);
  rx.ingest(bad_sequence, sizeof(bad_sequence), 50);
  assert(rx.state() == 3);

  rx.reset();
  rx.ingest(begin, sizeof(begin), 100);
  rx.expire(10101);
  assert(rx.state() == 3);

  rx.reset();
  const uint8_t bad_crc[] = {1, 9, 0, 0, 0, 0, 0};
  rx.ingest(bad_crc, sizeof(bad_crc), 1);
  rx.ingest(data, sizeof(data), 2);
  rx.ingest(end, sizeof(end), 3);
  assert(rx.state() == 3);

  rx.reset();
  const uint8_t one_byte[] = {1, 1, 0, 0, 0, 0, 0};
  const uint8_t overflow[] = {2, 0, 0, 'a', 'b'};
  rx.ingest(one_byte, sizeof(one_byte), 1);
  rx.ingest(overflow, sizeof(overflow), 2);
  assert(rx.state() == 3);

  rx.reset();
  rx.ingest(begin, sizeof(begin), 0xfffffff0U);
  rx.ingest(data, sizeof(data), 20);
  assert(rx.state() == 1 && rx.size() == 9);  // millis() wraparound.
  return 0;
}
