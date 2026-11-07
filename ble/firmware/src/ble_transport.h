#pragma once
#include <Arduino.h>

// Isolated BLE proof-of-concept; no local credentials or real data.
struct BleMessage { uint16_t length; uint8_t bytes[4096]; };
bool bleTransportBegin();
bool bleTakeMessage(BleMessage &message);
// Poll from the display thread and show the six digits locally. Never log it.
bool bleTakePasskey(uint32_t &passkey);
bool bleAuthenticated();
// Request a short pairing window only after an explicit local user action.
void bleOpenPairingWindow();
