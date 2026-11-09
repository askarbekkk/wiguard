// Forwards the LD2410C radar's UART (256000 baud on GPIO16/17) to the USB serial port unchanged.
// The laptop parses the radar frames (radar.py).
#include "driver/uart.h"

#define RADAR_UART UART_NUM_2
#define RADAR_RX_PIN 16  // radar TX -> ESP32 RX2
#define RADAR_TX_PIN 17  // radar RX <- ESP32 TX2

void app_main(void)
{
    uart_config_t radar = {
        .baud_rate = 256000,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    uart_driver_install(RADAR_UART, 2048, 0, 0, NULL, 0);
    uart_param_config(RADAR_UART, &radar);
    uart_set_pin(RADAR_UART, RADAR_TX_PIN, RADAR_RX_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);

    uart_driver_install(UART_NUM_0, 2048, 2048, 0, NULL, 0);  // USB side, 921600 from sdkconfig

    uint8_t buf[256];
    while (1) {
        int n = uart_read_bytes(RADAR_UART, buf, sizeof(buf), pdMS_TO_TICKS(20));
        if (n > 0) {
            uart_write_bytes(UART_NUM_0, buf, n);
        }
    }
}
