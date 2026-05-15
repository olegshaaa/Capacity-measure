#include <EEPROM.h>


#define A 37
#define B 36
#define C 35
#define D 34
#define E 33
#define F 32
#define G 31
#define DP 30
#define DIG1 22
#define DIG2 23
#define DIG3 24
#define DIG4 25

const uint8_t segmentMap[] = {
  0b00111111, 
  0b00000110, 
  0b01011011, 
  0b01001111, 
  0b01100110, 
  0b01101101, 
  0b01111101, 
  0b00000111, 
  0b01111111, 
  0b01101111
};


volatile byte disp[4] = {0, 0, 0, 0};
volatile byte digitIndex = 0;


const int MAX_SAMPLES = 1000;
const unsigned long LOG_INTERVAL_EEPROM = 1000;
unsigned long lastLog = 0;
unsigned long lastHeartbeat = 0;
unsigned long lastDispUpdate = 0; // Таймер для обновления экрана

bool isConnected = false;
int h_counter = 0;


uint8_t packVoltage(float v) {
  if (v < 0.50f) v = 0.50f;
  if (v > 1.77f) v = 1.77f;
  return (uint8_t)((v - 0.50f) * 100.0f + 0.5f);
}


// Функции дисплея
void writeSegments(byte num, bool dp) {
  uint8_t mask = segmentMap[num];
  digitalWrite(A, mask & 1); digitalWrite(B, (mask >> 1) & 1);
  digitalWrite(C, (mask >> 2) & 1); digitalWrite(D, (mask >> 3) & 1);
  digitalWrite(E, (mask >> 4) & 1); digitalWrite(F, (mask >> 5) & 1);
  digitalWrite(G, (mask >> 6) & 1); digitalWrite(DP, dp);
}

void disableAll() {
  digitalWrite(DIG1, LOW); digitalWrite(DIG2, LOW);
  digitalWrite(DIG3, LOW); digitalWrite(DIG4, LOW);
}

void showDigit(byte pos, byte val) {
  disableAll(); // Гасим всё перед переключением, чтобы убрать тени
  writeSegments(val, (pos == 0));
  if (pos == 0) digitalWrite(DIG1, HIGH);
  else if (pos == 1) digitalWrite(DIG2, HIGH);
  else if (pos == 2) digitalWrite(DIG3, HIGH);
  else digitalWrite(DIG4, HIGH);
}

void setupTimer1() {
  cli();
  TCCR1A = 0; TCCR1B = 0; TCNT1 = 0; OCR1A = 249;
  TCCR1B |= (1 << WGM12); TCCR1B |= (1 << CS11) | (1 << CS10);
  TIMSK1 |= (1 << OCIE1A);
  sei();
}


ISR(TIMER1_COMPA_vect) {
  byte pos = digitIndex;
  showDigit(pos, disp[pos]);
  digitIndex++;
  if(digitIndex > 3) digitIndex = 0;
}

// Функции EEPROM
int getSampleCount() {
  int count;
  EEPROM.get(0, count);
  if (count < 0 || count > MAX_SAMPLES) count = 0;
  return count;
}

void clearHistory() {
  int zero = 0;
  EEPROM.put(0, zero);
}

void setup() {
  int pins[] = {A, B, C, D, E, F, G, DP, DIG1, DIG2, DIG3, DIG4};
  for (int i = 0; i < 12; i++) pinMode(pins[i], OUTPUT);
  disableAll();
  Serial.begin(9600);
  setupTimer1();
}

void loop() {
  // Читаем АЦП
  uint32_t sum = 0;
  for (int i = 0; i < 16; i++) { 
    sum += analogRead(A0); 
    delayMicroseconds(100);
  }
  uint16_t adcValue = sum / 16;
  float voltage = adcValue * (4.889f / 1023.0f);

  unsigned long now = millis();

  
  if (now - lastDispUpdate > 330) {
    lastDispUpdate = now;
    uint16_t val = (uint16_t)(voltage * 1000.0f + 0.5f);
    
    // Атомарная запись (чтобы прерывание не прочитало наполовину измененный массив)
    cli(); 
    disp[0] = val / 1000;
    disp[1] = (val / 100) % 10;
    disp[2] = (val / 10) % 10;
    disp[3] = val % 10;
    sei();
  }

  
  while (Serial.available() > 0) {
    char incomingByte = Serial.read();
    if (incomingByte == 'H') {
      h_counter++;
      if (h_counter >= 2) {
        lastHeartbeat = now;
        if (!isConnected) {
          isConnected = true;
          int count = getSampleCount();
          if (count > 0) {
            for (int i = 0; i < count; i++) {
              uint8_t packedVal = EEPROM.read(2 + i);
              Serial.write(packedVal | 0b10000000); 
              delay(15);
            }
            clearHistory();
          }
        }
      }
    } else {
      h_counter = 0;
    }
  }

  if (now - lastHeartbeat > 2000) {
    isConnected = false;
    h_counter = 0; 
  }

  if (isConnected) {
    if (now - lastLog >= 1000) {
      lastLog = now;
      Serial.write(packVoltage(voltage) & 0b01111111);
    }
  } else {
    if (now - lastLog >= LOG_INTERVAL_EEPROM) {
      lastLog = now;
      int count = getSampleCount();
      if (count < MAX_SAMPLES) {
        EEPROM.write(2 + count, packVoltage(voltage));
        count++;
        EEPROM.put(0, count);
      }
    }
  }
}