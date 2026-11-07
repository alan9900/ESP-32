#pragma once
#include <stddef.h>
#include <stdint.h>

// BLE write frames are limited to the default 20-byte GATT payload.
// A separate per-frame application acknowledgement is required because the
// Arduino NimBLE wrapper delivers writes asynchronously after ATT response.
class FrameAssembler {
 public:
  static constexpr size_t MAX_MESSAGE = 4096;
  void reset();
  void expire(uint32_t now_ms);
  void ingest(const uint8_t *frame, size_t length, uint32_t now_ms);
  uint8_t state() const { return state_; }
  uint16_t nextSeq() const { return next_seq_; }
  size_t size() const { return used_; }
  const uint8_t *data() const { return payload_; }

 private:
  void fail();
  uint8_t payload_[MAX_MESSAGE]{};
  size_t expected_ = 0, used_ = 0;
  uint16_t next_seq_ = 0;
  uint32_t expected_crc_ = 0, last_ms_ = 0;
  uint8_t state_ = 0;
};
