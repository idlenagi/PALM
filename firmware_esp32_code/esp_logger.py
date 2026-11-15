import serial
import time
import csv
from datetime import datetime, timezone
from pathlib import Path

# ---------------- CONFIG ----------------
PORT = 'COM5'
BAUD = 921600                      # must match SERIAL_BAUD in the firmware
ESP_DIR = Path(r'C:\Users\Theresia\Documents\ESP32 Data')

RX_HEADER = ['run_label', 'pc_time_utc', 't_us', 'seq', 'interarrival_us',
             'proc_us', 'proc_full_us', 'lost', 'dup', 'ooo', 'qdrops', 'rssi']
SYS_HEADER = ['pc_time_utc', 't_us', 'event', 'value']
RX_FIELDS = 10                     # fields after the leading "rx"

# ---------------- FILES (one set per script start) ----------------
ESP_DIR.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
raw_path = ESP_DIR / f'esp32_raw_{stamp}.txt'    # every line, untouched (safety net)
rx_path = ESP_DIR / f'esp32_log_{stamp}.csv'     # parsed rx rows -> esp32_log.csv
sys_path = ESP_DIR / f'esp32_sys_{stamp}.csv'    # boot / reset / run_label / wifi events

run_label = 'unlabeled'
rx_count = 0
bad_lines = 0


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def handle_line(line, raw_f, rx_w, sys_w, rx_f, sys_f):
    """Parse one serial line. Raw copy is always kept."""
    global run_label, rx_count, bad_lines
    raw_f.write(f'{utc_now()},{line}\n')

    parts = line.split(',')
    kind = parts[0]

    if kind == 'rx':
        vals = parts[1:]
        if len(vals) != RX_FIELDS:
            bad_lines += 1
            return
        try:
            ints = [int(v) for v in vals]       # all numeric fields are integers
        except ValueError:
            bad_lines += 1
            return
        rx_w.writerow([run_label, utc_now()] + ints)
        rx_count += 1
        seq = ints[1]
        if seq == 0:
            print(f'[run start] label={run_label} (seq 0 received)')
        elif rx_count % 100 == 0:
            print(f'[{run_label}] {rx_count} rx rows logged (last seq {seq})')

    elif kind == 'sys' and len(parts) >= 4:
        t_us, event = parts[1], parts[2]
        value = ','.join(parts[3:])
        sys_w.writerow([utc_now(), t_us, event, value])
        if event == 'run_label':
            run_label = value
            rx_count = 0
        print(f'[sys] {event} = {value}')

    # anything else (boot ROM noise, partial lines) stays only in the raw file


def main():
    with open(raw_path, 'a', newline='') as raw_f, \
         open(rx_path, 'a', newline='') as rx_f, \
         open(sys_path, 'a', newline='') as sys_f:

        rx_w = csv.writer(rx_f)
        sys_w = csv.writer(sys_f)
        rx_w.writerow(RX_HEADER)
        sys_w.writerow(SYS_HEADER)

        print(f'Raw : {raw_path}\nRX  : {rx_path}\nSYS : {sys_path}')

        while True:
            try:
                print(f'Connecting to {PORT} @ {BAUD}...')
                ser = serial.Serial(PORT, BAUD, timeout=1)

                # Emulate Arduino IDE reboot so the ESP32 prints its boot header
                ser.dtr = True
                ser.rts = True
                time.sleep(0.05)
                ser.dtr = False
                ser.rts = False
                sys_w.writerow([utc_now(), '', 'logger_connected', PORT])

                while True:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if not line:
                        continue
                    handle_line(line, raw_f, rx_w, sys_w, rx_f, sys_f)
                    rx_f.flush()
                    sys_f.flush()
                    raw_f.flush()

            except serial.SerialException:
                sys_w.writerow([utc_now(), '', 'logger_disconnected', PORT])
                sys_f.flush()
                print('\nConnection lost (USB dropped). Waiting 2 seconds to reconnect...')
                time.sleep(2)
            except KeyboardInterrupt:
                print(f'\nStopped by user. {rx_count} rx rows in last run, '
                      f'{bad_lines} malformed lines skipped. Data saved.')
                break


if __name__ == '__main__':
    main()