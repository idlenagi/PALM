# Analysis scripts

| Script | Purpose | Report section |
|---|---|---|
| analyze_study.py | Participant analysis: per-participant medians, exact Wilcoxon tests, bootstrap intervals (10,000 resamples), plots | 5.5, 6 |
| analyze_infra.py | MQTT QoS benchmark analysis: round trip, loss, ESP32 share | 5.4, 6.5 |
| label_latency.py | Tool for marking action and response frames on the 120 fps video | 5.3 |
| label_pinch.py | Tool for marking the pinch-closed frame | 5.3, 6.3 |
| esp32_logger.py | PySerial logger for the ESP32 (921600 baud) | 4.3 |

Install: `pip install -r requirements.txt`

Participant analysis (run from the repository root):

    python analysis/analyze_study.py --device Participant_data/device_metrics/P0*_device_metrics.csv \
      --video Participant_data/latency_video.csv --observer Participant_data/observer_labels.csv \
      --surveys Participant_data/surveys.csv --participants Participant_data/participants.csv --out results

Session videos are not shared, so the labelling tools need your own video files.
