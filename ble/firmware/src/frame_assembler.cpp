#include "frame_assembler.h"
#include <string.h>

namespace {
constexpr uint32_t FRAME_TIMEOUT_MS = 10000;
uint16_t le16(const uint8_t *p) { return static_cast<uint16_t>(p[0] | (static_cast<uint16_t>(p[1]) << 8)); }
uint32_t le32(const uint8_t *p) { return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) | (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24); }
uint32_t crc32(const uint8_t *p, size_t n) {
  uint32_t crc = 0xffffffffU;
  for (size_t i = 0; i < n; ++i) {
    crc ^= p[i];
    for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
  }
  return ~crc;
}
}
void FrameAssembler::reset() { expected_ = used_ = 0; next_seq_ = 0; expected_crc_ = last_ms_ = 0; state_ = 0; }
void FrameAssembler::fail() { expected_ = used_ = 0; next_seq_ = 0; state_ = 3; }
void FrameAssembler::expire(uint32_t now_ms) { if (state_ == 1 && now_ms - last_ms_ > FRAME_TIMEOUT_MS) fail(); }
void FrameAssembler::ingest(const uint8_t *f, size_t n, uint32_t now_ms) {
  expire(now_ms);
  if (!f || n == 0 || n > 20) { fail(); return; }
  if (f[0] == 1) {
    if (n != 7) { fail(); return; }
    const size_t length = le16(f + 1);
    if (length == 0 || length > MAX_MESSAGE) { fail(); return; }
    expected_ = length; used_ = 0; next_seq_ = 0; expected_crc_ = le32(f + 3); state_ = 1; last_ms_ = now_ms; return;
  }
  if (state_ != 1) { fail(); return; }
  if (f[0] == 2) {
    if (n < 4 || le16(f + 1) != next_seq_ || used_ + n - 3 > expected_) { fail(); return; }
    memcpy(payload_ + used_, f + 3, n - 3); used_ += n - 3; ++next_seq_; last_ms_ = now_ms; return;
  }
  if (f[0] == 3 && n == 1 && used_ == expected_ && crc32(payload_, used_) == expected_crc_) {
    state_ = 2; last_ms_ = now_ms; return;
  }
  fail();
}
