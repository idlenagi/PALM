"""
Join mqtt_run.csv (tablet) with esp32_log.csv (ESP32 serial) and summarize.

Usage:
  python analyze_infra.py --mqtt mqtt_run.csv --esp esp32_log_20261025_120000.csv
  python analyze_infra.py --mqtt mqtt_run.csv --esp esp32_log.csv --device device_metrics.csv --out results

Expected columns
  mqtt_run.csv      : run_label,broker,qos,seq,t_send_us,rtt_us,esp_proc_us
  esp32_log.csv     : run_label,pc_time_utc,t_us,seq,interarrival_us,proc_us,
                      proc_full_us,lost,dup,ooo,qdrops,rssi
  device_metrics.csv: needs frame_ms, inference_ms; optional participant_id, mode
"""
import argparse
import numpy as np
import pandas as pd


def read_csv_any(path, **kw):
    """Read a CSV that may be UTF-8, UTF-8 with BOM, or UTF-16 (e.g. PowerShell redirect)."""
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return pd.read_csv(path, encoding="latin-1", **kw)

DROP_MS = 1000 / 60  # 16.7 ms: a frame slower than this counts as dropped


def p95(s):
    s = s.dropna()
    return s.quantile(0.95) if len(s) else np.nan


def p99(s):
    s = s.dropna()
    return s.quantile(0.99) if len(s) else np.nan


def network_summary(mqtt, esp):
    # Keep the first ESP32 row per (run, seq); duplicates are counted separately.
    esp_u = esp.sort_values('t_us').drop_duplicates(['run_label', 'seq'], keep='first')
    df = mqtt.merge(esp_u, on=['run_label', 'seq'], how='left', suffixes=('', '_esp'))

    df['echoed'] = df['rtt_us'].notna()
    df['esp_received'] = df['proc_us'].notna()
    df['rtt_ms'] = df['rtt_us'] / 1000
    df['proc_full_ms'] = df['proc_full_us'] / 1000
    # Approximate transit = RTT minus ESP32 internal time (two network legs + broker)
    df['transit_ms'] = (df['rtt_us'] - df['proc_full_us']) / 1000

    g = df.groupby(['run_label', 'qos'])
    out = g.agg(
        sent=('seq', 'size'),
        echoed=('echoed', 'sum'),
        esp_received=('esp_received', 'sum'),
        rtt_median_ms=('rtt_ms', 'median'),
        rtt_p95_ms=('rtt_ms', p95),
        rtt_p99_ms=('rtt_ms', p99),
        rtt_max_ms=('rtt_ms', 'max'),
        transit_median_ms=('transit_ms', 'median'),
        esp_proc_median_us=('proc_us', 'median'),
        esp_proc_p95_us=('proc_us', p95),
        esp_proc_full_median_us=('proc_full_us', 'median'),
        esp_proc_full_p95_us=('proc_full_us', p95),
        rssi_mean=('rssi', 'mean'),
    )
    out['tablet_loss_pct'] = 100 * (1 - out['echoed'] / out['sent'])
    out['esp_missed_pct'] = 100 * (1 - out['esp_received'] / out['sent'])
    out['esp_share_of_rtt_pct'] = 100 * (out['esp_proc_full_median_us'] / 1000) / out['rtt_median_ms']

    # ESP32 counters are cumulative within a run, so take the last value
    last = (esp.sort_values('t_us').groupby('run_label')
               [['lost', 'dup', 'ooo', 'qdrops']].last())
    out = out.reset_index().merge(last, on='run_label', how='left')
    return out.round(3), df


def device_summary(dev):
    dev = dev.copy()
    dev['fps'] = 1000 / dev['frame_ms'].replace(0, np.nan)
    dev['dropped'] = dev['frame_ms'] > DROP_MS
    keys = [k for k in ['mode', 'run_label'] if k in dev.columns][:1] or ['run_label']
    g = dev.groupby(keys)
    out = g.agg(
        frames=('frame_ms', 'size'),
        frame_median_ms=('frame_ms', 'median'),
        frame_p95_ms=('frame_ms', p95),
        fps_median=('fps', 'median'),
        drop_rate_pct=('dropped', lambda s: 100 * s.mean()),
        build_p95_ms=('build_ms', p95),
        raster_p95_ms=('raster_ms', p95),
        inference_median_ms=('inference_ms', 'median'),
        inference_p95_ms=('inference_ms', p95),
    )
    return out.round(3)


def paired_test(dev, metric='frame_ms'):
    """Touch vs gesture on per-participant medians (needs participant_id + mode)."""
    if not {'participant_id', 'mode', metric} <= set(dev.columns):
        return None
    from scipy import stats
    per = dev.groupby(['participant_id', 'mode'])[metric].median().unstack('mode').dropna()
    if not {'touch', 'gesture'} <= set(per.columns) or len(per) < 3:
        return None
    w = stats.wilcoxon(per['touch'], per['gesture'])
    return per.round(3), w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mqtt', required=True)
    ap.add_argument('--esp', nargs='+', default=[])
    ap.add_argument('--warmup-events', type=int, default=5,
                    help='drop the first N events (seq < N) of each run as warm-up (default 5)')
    ap.add_argument('--device')
    ap.add_argument('--out', default='summary')
    a = ap.parse_args()

    mqtt = read_csv_any(a.mqtt)
    if a.esp:
        esp = pd.concat([read_csv_any(f) for f in a.esp], ignore_index=True)
    else:
        print('NOTE: no --esp file given; ESP32 columns will be empty.')
        esp = pd.DataFrame(columns=['run_label', 'seq', 't_us', 'interarrival_us', 'proc_us',
                                    'proc_full_us', 'lost', 'dup', 'ooo', 'qdrops', 'rssi'])
    if a.warmup_events > 0:
        n0 = len(mqtt)
        mqtt = mqtt[mqtt['seq'] >= a.warmup_events]
        if len(esp):
            esp = esp[esp['seq'] >= a.warmup_events]
        print(f'Warm-up: dropped the first {a.warmup_events} events per run ({n0 - len(mqtt)} tablet rows).')

    net, merged = network_summary(mqtt, esp)
    print('\n=== NETWORK / ESP32 (per run) ===')
    print(net.to_string(index=False))
    net.to_csv(f'{a.out}_network.csv', index=False)
    merged.to_csv(f'{a.out}_merged_events.csv', index=False)

    if a.device:
        dev = read_csv_any(a.device, low_memory=False)
        ds = device_summary(dev)
        print('\n=== DEVICE (tablet) ===')
        print(ds.to_string())
        ds.to_csv(f'{a.out}_device.csv')
        res = paired_test(dev)
        if res:
            per, w = res
            print('\n=== Paired test on per-participant median frame_ms ===')
            print(per.to_string())
            print(f'Wilcoxon signed-rank: W={w.statistic:.3f}, p={w.pvalue:.4f} '
                  f'(n={len(per)}; pilot, interpret cautiously)')


if __name__ == '__main__':
    main()
