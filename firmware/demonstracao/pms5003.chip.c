// PMS5003 UART simulation for Wokwi. See README.md for model assumptions.
#include "wokwi-api.h"
#include <stdlib.h>
#include <string.h>

#define FRAME_SIZE 32
#define COMMAND_SIZE 7
#define AUTO_VALUE UINT32_MAX
#define TICK_US 10000

typedef struct {
  pin_t set_pin, reset_pin;
  uart_dev_t uart;
  uint32_t pm[3], cf1[3], particles[6];
  uint32_t interval_attr, warmup_attr, fault_attr;
  uint8_t command[COMMAND_SIZE], command_size;
  uint8_t frame[FRAME_SIZE];
  bool active, sleep_command, running, tx_busy, read_pending;
  uint64_t ready_at, next_frame_at, last_rx_at;
} chip_state_t;

static uint64_t now_ms(void) { return get_sim_nanos() / 1000000; }
static uint32_t min_u32(uint32_t a, uint32_t b) { return a < b ? a : b; }
static uint16_t u16(uint32_t value) { return (uint16_t)min_u32(value, 65535); }

static void put_u16(uint8_t *dest, uint16_t value) {
  dest[0] = value >> 8;
  dest[1] = value & 255;
}

static uint16_t checksum(const uint8_t *data, uint8_t size) {
  uint16_t sum = 0;
  for (uint8_t i = 0; i < size; i++) sum += data[i];
  return sum;
}

static uint16_t optional_value(uint32_t attr, uint16_t fallback) {
  uint32_t value = attr_read(attr);
  return value == AUTO_VALUE ? fallback : u16(value);
}

static void build_frame(chip_state_t *chip) {
  uint16_t pm25 = u16(attr_read(chip->pm[1]));
  uint16_t pm1 = u16(min_u32(attr_read(chip->pm[0]), pm25));
  uint16_t pm10 = u16(attr_read(chip->pm[2]));
  if (pm10 < pm25) pm10 = pm25;
  uint16_t mass[3] = {pm1, pm25, pm10};

  // Deterministic fixtures, not a physical mass-to-particle conversion.
  uint32_t counts[6];
  counts[5] = 0;
  counts[4] = (pm10 - pm25) / 40;
  counts[3] = counts[4] + (pm10 - pm25) / 5;
  counts[2] = counts[3] + (pm25 - pm1) * 2;
  counts[1] = counts[2] + pm1 * 20;
  counts[0] = counts[1] + pm1 * 80;

  memset(chip->frame, 0, FRAME_SIZE);
  chip->frame[0] = 0x42;
  chip->frame[1] = 0x4d;
  put_u16(chip->frame + 2, 28);
  for (uint8_t i = 0; i < 3; i++) {
    put_u16(chip->frame + 4 + 2 * i,
            optional_value(chip->cf1[i], mass[i]));
    put_u16(chip->frame + 10 + 2 * i, mass[i]);
  }
  for (uint8_t i = 0; i < 6; i++) {
    put_u16(chip->frame + 16 + 2 * i,
            optional_value(chip->particles[i], u16(counts[i])));
  }
  // Bytes 28 and 29 are reserved in the V2.3 manual; keep both zero.
  uint16_t sum = checksum(chip->frame, 30);
  if (attr_read(chip->fault_attr) == 1) sum ^= 1;
  put_u16(chip->frame + 30, sum);
}

static void update_running(chip_state_t *chip) {
  bool running = pin_read(chip->reset_pin) == HIGH &&
                 pin_read(chip->set_pin) == HIGH && !chip->sleep_command;
  if (running && !chip->running) {
    // Suppressing unstable readings is a deliberate simplification.
    chip->ready_at = now_ms() + min_u32(attr_read(chip->warmup_attr), 60000);
    chip->next_frame_at = chip->ready_at;
  }
  if (!running) chip->read_pending = false;
  chip->running = running;
}

static void on_pin_change(void *user_data, pin_t pin, uint32_t value) {
  chip_state_t *chip = user_data;
  if (pin == chip->reset_pin && value == LOW) {
    chip->active = true;
    chip->sleep_command = false;
    chip->command_size = 0;
    chip->read_pending = false;
  }
  update_running(chip);
}

static void on_write_done(void *user_data) {
  ((chip_state_t *)user_data)->tx_busy = false;
}

static void execute_command(chip_state_t *chip) {
  uint8_t cmd = chip->command[2];
  uint8_t value = chip->command[4];
  // DATAH is unspecified (X) in the manual. E2 ignores both data bytes.
  if (cmd == 0xe1 && value <= 1) {
    chip->active = value == 1;
    chip->read_pending = false;
    if (chip->active) chip->next_frame_at = now_ms();
  } else if (cmd == 0xe2) {
    if (!chip->active && chip->running && now_ms() >= chip->ready_at)
      chip->read_pending = true;
  } else if (cmd == 0xe4 && value <= 1) {
    chip->sleep_command = value == 0;
    update_running(chip);
  }
  // V2.3 defines a data reply for E2 only. No invented E1/E4 ACKs.
}

static void drop_command_byte(chip_state_t *chip) {
  chip->command_size--;
  memmove(chip->command, chip->command + 1, chip->command_size);
}

static void on_rx_data(void *user_data, uint8_t byte) {
  chip_state_t *chip = user_data;
  if (pin_read(chip->reset_pin) == LOW) return;
  uint64_t time = now_ms();
  if (time - chip->last_rx_at > 100) chip->command_size = 0;
  chip->last_rx_at = time;
  chip->command[chip->command_size++] = byte;

  // Sliding resynchronization also recovers headers inside damaged packets.
  while (chip->command_size) {
    if (chip->command[0] != 0x42 ||
        (chip->command_size >= 2 && chip->command[1] != 0x4d)) {
      drop_command_byte(chip);
      continue;
    }
    if (chip->command_size < COMMAND_SIZE) break;
    uint16_t received = ((uint16_t)chip->command[5] << 8) | chip->command[6];
    if (checksum(chip->command, 5) == received) {
      execute_command(chip);
      chip->command_size = 0;
    } else {
      drop_command_byte(chip);
    }
  }
}

static void on_tick(void *user_data) {
  chip_state_t *chip = user_data;
  update_running(chip);
  uint64_t time = now_ms();
  if (!chip->running || time < chip->ready_at || chip->tx_busy) return;
  if (chip->active ? time < chip->next_frame_at : !chip->read_pending) return;

  uint32_t period = min_u32(attr_read(chip->interval_attr), 60000);
  if (period < 200) period = 200;
  chip->next_frame_at = time + period;
  chip->read_pending = false;
  if (attr_read(chip->fault_attr) == 2) return;

  build_frame(chip);
  // Keep this buffer intact until Wokwi finishes the asynchronous write.
  chip->tx_busy = uart_write(chip->uart, chip->frame, FRAME_SIZE);
}

void chip_init(void) {
  chip_state_t *chip = calloc(1, sizeof(*chip));
  if (!chip) return;
  pin_init("VCC", INPUT);
  pin_init("GND", INPUT);
  chip->set_pin = pin_init("SET", INPUT_PULLUP);
  chip->reset_pin = pin_init("RESET", INPUT_PULLUP);
  chip->active = true;
  chip->pm[0] = attr_init("pm1", 8);
  chip->pm[1] = attr_init("pm25", 12);
  chip->pm[2] = attr_init("pm10", 18);
  chip->cf1[0] = attr_init("cf1Pm1", AUTO_VALUE);
  chip->cf1[1] = attr_init("cf1Pm25", AUTO_VALUE);
  chip->cf1[2] = attr_init("cf1Pm10", AUTO_VALUE);
  const char *count_names[] = {
    "particles03", "particles05", "particles10",
    "particles25", "particles50", "particles100"
  };
  for (uint8_t i = 0; i < 6; i++)
    chip->particles[i] = attr_init(count_names[i], AUTO_VALUE);
  chip->interval_attr = attr_init("intervalMs", 2300);
  chip->warmup_attr = attr_init("warmupMs", 30000);
  chip->fault_attr = attr_init("fault", 0);

  const uart_config_t uart_config = {
    .rx = pin_init("RX", INPUT),
    .tx = pin_init("TX", INPUT_PULLUP),
    .baud_rate = 9600,
    .rx_data = on_rx_data,
    .write_done = on_write_done,
    .user_data = chip,
  };
  chip->uart = uart_init(&uart_config);
  const pin_watch_config_t watch_config = {
    .edge = BOTH, .pin_change = on_pin_change, .user_data = chip,
  };
  pin_watch(chip->set_pin, &watch_config);
  pin_watch(chip->reset_pin, &watch_config);
  const timer_config_t timer_config = {
    .callback = on_tick, .user_data = chip,
  };
  timer_t timer = timer_init(&timer_config);
  update_running(chip);
  timer_start(timer, TICK_US, true);
}
