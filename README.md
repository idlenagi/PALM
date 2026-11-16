# PALM: Pinch or Tap?
Pilot study of Accuracy, Latency and Mental workload: touch versus hand-gesture input in a tablet game.

Author: Theresia Mulyadi (112006221), undergraduate capstone, November 2026.

## What this project is

AetherGrid is a Flutter game in which players select multiples of 3, 4 or 5 on a board, either by **tapping** the screen or by **pinching in mid-air** in front of the front camera. Game events are sent over MQTT to a Mosquitto broker, and an ESP32 echo node times the messaging path independently of the player. A 120 fps phone video of the hand and screen gives end-to-end latency, which in-app timers cannot measure.

Main findings of the six-participant pilot (details in the report):

| Measure | Touch | Gesture |
|---|---|---|
| End-to-end latency, video (ms) | 41.7 | 166.7 |
| In-app latency (ms) | not comparable | about 26 |
| Selection time (ms) | 710 | 1521 |
| First-attempt accuracy | 0.96 | 0.94 |
| Frame time, 95th percentile (ms) | 10.7 | 32.0 |
| SUS (0 to 100) | 86.3 | 75.0 |

Gesture was slower for all six participants and touch was preferred by all six. With six participants, only a brief familiarization and one tablet, these are pilot estimates, not general claims. See the report for limitations.

## Repository layout

```
Aether_Grid_App/        Flutter app (the game, input modes, logging, MQTT client)
firmware_esp32_code/    ESP32 echo node (copy secrets.example.h to secrets.h)
Participant_data/       per-participant game logs (device_metrics/), video latency,
                        pinch frames, observer labels, frame_marking_check/,
                        surveys.csv, participants.csv
Benchmark/              MQTT QoS benchmark, 7 Nov and 12 Nov (tablet and ESP32 logs, summaries)
analysis/               scripts that produce the tables and figures in the report,
                        and esp32_logger.py (reads the ESP32 serial log)
```

## Requirements

- Flutter (stable; run `flutter --version` and write the version here), with the Android toolchain
- An Android tablet. The study used a Xiaomi Pad 6 with the front camera
- Mosquitto MQTT broker on a laptop on the same network (the study used a personal hotspot)
- ESP32 board and the Arduino or PlatformIO toolchain for the firmware
- Python 3 for `analysis/` (`pip install -r analysis/requirements.txt`)

Hand tracking uses the [`hand_detection`](https://github.com/hugocornellier/hand_detection) Flutter package, version 4.3.1 (Apache-2.0), an implementation of Google's MediaPipe hand detection and landmark models on TensorFlow Lite. It is pinned in `pubspec.lock`.

## Running the app

1. Start Mosquitto on the laptop and note its IP address.
2. Connect the tablet with USB debugging on.
3. From `Aether_Grid_App/`:

```bash
flutter pub get
flutter run --release --dart-define=MQTT_HOST=<laptop IP address>
```

The broker address is passed at build time with `--dart-define=MQTT_HOST=...`, so no address is stored in the source. In touch mode the camera stays off. Hints are disabled for the study.

## Running the ESP32 echo node

1. Copy `firmware_esp32_code/secrets.example.h` to `firmware_esp32_code/secrets.h` and fill in your Wi-Fi and broker details. `secrets.h` is ignored by git and must never be committed.
2. Build and flash the firmware.
3. On the laptop, run `python analysis/esp32_logger.py` to record the node's own timings from the USB serial port.

Note: the firmware as used in the study loses a share of QoS 1 echoes because of how the node handles MQTT, so QoS 1 results reflect that firmware and not the protocol (see report, Sections 6.5 and 7.3).

## Reproducing the results

`Participant_data/` and `Benchmark/` contain the logs, marked frame numbers, observer labels, questionnaires and benchmark data. Run the scripts in `analysis/` to regenerate the tables and figures, for example:

```bash
python analysis/analyze_study.py --device Participant_data/device_metrics/P0*_device_metrics.csv \
  --video Participant_data/latency_video.csv --observer Participant_data/observer_labels.csv \
  --surveys Participant_data/surveys.csv --participants Participant_data/participants.csv --out results
```

The differences in the report's results table are medians of the per-participant paired differences (gesture minus touch). Latency in milliseconds is `(frame_response - frame_action) / 120 * 1000`. Tests are exact two-sided Wilcoxon signed-rank tests, and intervals are bootstrap 95% intervals of the mean paired difference (10,000 resamples).

Session videos are **not** included, because participants were told they would not be published. Participants appear only as P01 to P06.

## Known limitations

- Six participants, aged 21 to 22, no gesture experience, one tablet, one task
- Only a brief, unrecorded familiarization (moving between selections versus selecting), so gesture results may include early learning
- Touch always used table order 3, 4, 5 and gesture 5, 4, 3, so table order is partly tied to mode
- Hand tracking ran at a median of 12.5 frames per second against a 20 target
- Display refresh rate was left on automatic and not logged
- Frame marking is subjective: median differences between three raters were 1 to 5 frames, with single-trial differences up to 20 frames

## Third-party software

- `hand_detection` 4.3.1 (Apache-2.0), based on Google MediaPipe models
- Flutter and Dart packages listed in `pubspec.yaml`
- Eclipse Mosquitto MQTT broker

## License

Apache-2.0. See the `LICENSE` file.

## Citation

Mulyadi, T. (2026). *Pinch or Tap? Touch versus Hand-Gesture Input in a Tablet Game. PALM: A Pilot Study of Accuracy, Latency and Mental Workload.* Undergraduate capstone report.
