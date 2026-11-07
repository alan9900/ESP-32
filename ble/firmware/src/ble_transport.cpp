#include "ble_transport.h"
#include "frame_assembler.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLESecurity.h>
#include <host/ble_hs.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

// Arduino ESP32 3.3.5 otherwise deletes an existing bond automatically when
// a peer requests repeat pairing. Intercept only that event and preserve the
// library's handling of all other GAP events. The pinned platform and this
// exact symbol are verified at link time and in the ELF before hardware tests.
extern "C" int __real__ZN9BLEServer21handleGATTServerEventEP13ble_gap_eventPv(struct ble_gap_event *, void *);
// With this pinned Arduino BLE version, disable its unsolicited security
// request at connect time. Protected GATT reads/writes still require MITM and
// encryption and cause the central to negotiate security before access.
extern "C" bool ble_force_security asm("_ZN11BLESecurity15m_forceSecurityE");
extern "C" int __wrap__ZN9BLEServer21handleGATTServerEventEP13ble_gap_eventPv(struct ble_gap_event *event, void *arg) {
  if (event && event->type == BLE_GAP_EVENT_REPEAT_PAIRING) {
    Serial.println("[ble] repeat pairing refused");
    return BLE_GAP_REPEAT_PAIRING_IGNORE;
  }
  if (event && event->type == BLE_GAP_EVENT_DISCONNECT) {
    Serial.printf("[ble] disconnect reason=%d\n", event->disconnect.reason);
  }
  if (event && event->type == BLE_GAP_EVENT_ENC_CHANGE) {
    Serial.printf("[ble] encryption status=%d\n", event->enc_change.status);
  }
  return __real__ZN9BLEServer21handleGATTServerEventEP13ble_gap_eventPv(event, arg);
}

namespace {
constexpr char serviceUUID[] = "8bf540f4-54ca-49cf-b7e5-e191b62a0001";
constexpr char writeUUID[] = "8bf540f4-54ca-49cf-b7e5-e191b62a0002";
constexpr char statusUUID[] = "8bf540f4-54ca-49cf-b7e5-e191b62a0003";
QueueHandle_t inbox, passkeys;
SemaphoreHandle_t lock;
FrameAssembler assembler;
BleMessage completedMessage;
BLECharacteristic *statusCharacteristic;
BLEServer *bleServer;
volatile bool authenticated = false;
volatile uint16_t activeHandle = 0xffff;
volatile uint32_t pairingDeadline = 0;

bool secure(const ble_gap_conn_desc *d) {
  return d && d->sec_state.encrypted && d->sec_state.authenticated && d->sec_state.bonded && d->sec_state.key_size == 16;
}
void publishStatus() {
  uint16_t seq = assembler.nextSeq();
  uint8_t status[] = {assembler.state(), static_cast<uint8_t>(seq), static_cast<uint8_t>(seq >> 8)};
  statusCharacteristic->setValue(status, sizeof(status));
}
class SecurityCallbacks : public BLESecurityCallbacks {
  void onPassKeyNotify(uint32_t pin) override {
    Serial.println("[ble] passkey requested");
    if (!pairingDeadline || static_cast<int32_t>(pairingDeadline - millis()) <= 0) {
      if (bleServer && activeHandle != 0xffff) bleServer->disconnect(activeHandle);
      return;
    }
    xQueueOverwrite(passkeys, &pin);
  }
  void onAuthenticationComplete(ble_gap_conn_desc *d) override {
    authenticated = d && d->conn_handle == activeHandle && secure(d);
    Serial.printf("[ble] security encrypted=%d authenticated=%d bonded=%d key_size=%d accepted=%d\n",
                  d ? d->sec_state.encrypted : 0, d ? d->sec_state.authenticated : 0,
                  d ? d->sec_state.bonded : 0, d ? d->sec_state.key_size : 0, authenticated);
    if (authenticated) { pairingDeadline = 0; xQueueReset(passkeys); }
  }
  bool onConfirmPIN(uint32_t) override { return false; }
};
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *server, ble_gap_conn_desc *d) override {
    // The framework increments the connection count after this callback.
    if (server->getConnectedCount() >= 1) { server->disconnect(d->conn_handle); return; }
    activeHandle = d->conn_handle;
    // Windows may deliver an encryption event before the server's onConnect
    // callback. Preserve already-established authenticated link security.
    authenticated = secure(d);
    if (authenticated) { pairingDeadline = 0; xQueueReset(passkeys); }
    Serial.println("[ble] connected");
    xSemaphoreTake(lock, portMAX_DELAY); assembler.reset(); publishStatus(); xSemaphoreGive(lock);
  }
  void onDisconnect(BLEServer *, ble_gap_conn_desc *d) override {
    if (!d || d->conn_handle != activeHandle) return;
    authenticated = false;
    activeHandle = 0xffff;
    Serial.println("[ble] disconnected");
    xSemaphoreTake(lock, portMAX_DELAY); assembler.reset(); publishStatus(); xSemaphoreGive(lock);
    xQueueReset(inbox); xQueueReset(passkeys);
  }
};
class WriteCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c, ble_gap_conn_desc *d) override {
    if (!secure(d) || !authenticated || d->conn_handle != activeHandle) return;
    const String frame = c->getValue();
    xSemaphoreTake(lock, portMAX_DELAY);
    assembler.ingest(reinterpret_cast<const uint8_t *>(frame.c_str()), frame.length(), millis());
    if (assembler.state() == 2) {
      completedMessage.length = assembler.size(); memcpy(completedMessage.bytes, assembler.data(), completedMessage.length);
      xQueueOverwrite(inbox, &completedMessage);
    }
    publishStatus();
    xSemaphoreGive(lock);
  }
};
class StatusCallbacks : public BLECharacteristicCallbacks {
  void onRead(BLECharacteristic *, ble_gap_conn_desc *d) override {
    if (!secure(d) || !authenticated || d->conn_handle != activeHandle) return;
    xSemaphoreTake(lock, portMAX_DELAY); assembler.expire(millis()); publishStatus(); xSemaphoreGive(lock);
  }
};
}
bool bleTransportBegin() {
#if !defined(CONFIG_NIMBLE_ENABLED)
  return false;
#else
  inbox = xQueueCreate(1, sizeof(BleMessage)); passkeys = xQueueCreate(1, sizeof(uint32_t)); lock = xSemaphoreCreateMutex();
  if (!inbox || !passkeys || !lock) return false;
  BLEDevice::init("ESP32-C6-Desk");
  BLESecurity::setPassKey(false);
  BLESecurity::regenPassKeyOnConnect(true);
  BLESecurity::setCapability(ESP_IO_CAP_OUT);
  BLESecurity::setAuthenticationMode(true, true, true);
  ble_force_security = false;
  ble_hs_cfg.sm_sc_only = 1; // Do not silently fall back to legacy pairing.
  BLEDevice::setSecurityCallbacks(new SecurityCallbacks());
  BLEServer *server = BLEDevice::createServer(); bleServer = server; server->setCallbacks(new ServerCallbacks()); server->advertiseOnDisconnect(true);
  BLEService *service = server->createService(serviceUUID);
  auto *write = service->createCharacteristic(writeUUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_AUTHEN);
  write->setCallbacks(new WriteCallbacks());
  statusCharacteristic = service->createCharacteristic(statusUUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_READ_AUTHEN);
  statusCharacteristic->setCallbacks(new StatusCallbacks());
  publishStatus();
  service->start();
  BLEAdvertising *advertising = BLEDevice::getAdvertising(); advertising->addServiceUUID(serviceUUID); advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
  return true;
#endif
}
bool bleTakeMessage(BleMessage &m) { return inbox && xQueueReceive(inbox, &m, 0) == pdTRUE; }
bool bleTakePasskey(uint32_t &key) { return passkeys && xQueueReceive(passkeys, &key, 0) == pdTRUE; }
bool bleAuthenticated() { return authenticated; }
void bleOpenPairingWindow() { pairingDeadline = millis() + 120000U; }
