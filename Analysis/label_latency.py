"""
Frame-by-frame latency labeller for the 120 fps phone video.

Install once:   pip install opencv-python pandas

Keys (click the video window first):
  d / a   next / previous frame          c / z   +10 / -10 frames        v / x   +60 / -60 frames
  k       mark ACTION frame (finger contact for touch, pinch starts closing for gesture)
  l       mark RESPONSE frame (first frame where the screen visibly responds)
  u       clear both marks for this trial
  t       type a note for this trial (in the terminal window)
  s       SAVE this trial to the CSV and go to the next trial
  n       skip this trial without saving (draw a replacement yourself and re-run with --trials)
  p       go back to the previous trial
  q       quit
"""
import argparse
import csv
import os
import random
import sys

import pandas as pd

COLUMNS = ["participant_id", "mode", "trial_id", "video_file", "fps",
           "frame_action", "frame_response", "latency_ms", "notes"]


def read_csv_any(path, **kw):
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return pd.read_csv(path, encoding="latin-1", **kw)


def pick_trials(device_csv, participant, mode, n, seed):
    """Randomly draw n trial ids that have a selection row in the game log."""
    d = read_csv_any(device_csv, low_memory=False)
    if "event" in d.columns:
        d = d[d["event"] == "selection"]
    if "participant_id" in d.columns:
        d = d[d["participant_id"].astype(str) == str(participant)]
    if "mode" in d.columns:
        d = d[d["mode"].astype(str) == str(mode)]
    ids = sorted(pd.to_numeric(d["trial_id"], errors="coerce").dropna().astype(int).unique().tolist())
    if not ids:
        sys.exit("No selection rows found for that participant/mode in the device file.")
    rng = random.Random(seed)
    k = min(n, len(ids))
    return sorted(rng.sample(ids, k)), len(ids)


def load_rows(csv_path):
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_row(csv_path, row):
    """Add the row, replacing an existing one with the same participant + mode + trial."""
    rows = load_rows(csv_path)
    key = (str(row["participant_id"]), str(row["mode"]), str(row["trial_id"]))
    rows = [r for r in rows if (r.get("participant_id"), r.get("mode"), r.get("trial_id")) != key]
    rows.append({c: row.get(c, "") for c in COLUMNS})
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


class Video:
    """Frame access: sequential reads for +1 steps, a seek for everything else."""

    def __init__(self, path):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            sys.exit(f"Cannot open video: {path}")
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.file_fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.pos = -1
        self.img = None

    def get(self, i):
        i = max(0, min(self.n - 1, i))
        if i == self.pos and self.img is not None:
            return self.img, i
        if i != self.pos + 1:
            self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, i)
        ok, img = self.cap.read()
        if not ok:
            return self.img, self.pos
        self.pos, self.img = i, img
        return img, i


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--participant", required=True)
    ap.add_argument("--mode", required=True, choices=["touch", "gesture"])
    ap.add_argument("--trials", nargs="+", type=int, help="trial ids to label")
    ap.add_argument("--device", help="device_metrics CSV to draw random trials from")
    ap.add_argument("--n", type=int, default=5, help="how many trials to draw (default 5)")
    ap.add_argument("--seed", type=int, default=1, help="random seed for the draw")
    ap.add_argument("--fps", type=float, default=120.0, help="real capture rate (default 120)")
    ap.add_argument("--csv", default="latency_video.csv")
    ap.add_argument("--width", type=int, default=1280, help="display width in pixels")
    a = ap.parse_args()

    if a.trials:
        trials = list(a.trials)
    elif a.device:
        trials, total = pick_trials(a.device, a.participant, a.mode, a.n, a.seed)
        plan = f"latency_trials_{a.participant}_{a.mode}.txt"
        with open(plan, "w", encoding="utf-8") as f:
            f.write(f"participant={a.participant} mode={a.mode} seed={a.seed} drawn={len(trials)} of {total}\n")
            f.write(" ".join(map(str, trials)) + "\n")
        print(f"Drew {len(trials)} of {total} trials (seed {a.seed}): {trials}. Saved the draw to {plan}")
    else:
        sys.exit("Give --trials or --device.")

    import cv2
    vid = Video(a.video)
    print(f"Video: {vid.n} frames, file reports {vid.file_fps:.2f} fps. "
          f"Using real capture rate {a.fps:g} fps ({1000 / a.fps:.2f} ms per frame).")
    video_name = os.path.basename(a.video)

    state = {t: {"action": None, "response": None, "note": ""} for t in trials}
    ti, frame = 0, 0
    win = "label_latency"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while True:
        t = trials[ti]
        st = state[t]
        img, frame = vid.get(frame)
        h, w = img.shape[:2]
        scale = a.width / w
        show = cv2.resize(img, (a.width, int(h * scale))) if scale != 1 else img.copy()

        def txt(s, y, color=(255, 255, 255)):
            cv2.putText(show, s, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(show, s, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

        txt(f"{a.participant} {a.mode}  trial {t}  ({ti + 1}/{len(trials)})", 28)
        txt(f"frame {frame} / {vid.n - 1}   t = {frame / a.fps:.3f} s", 56)
        txt(f"action: {st['action']}   response: {st['response']}", 84,
            (0, 255, 0) if st["action"] is not None and st["response"] is not None else (0, 215, 255))
        if st["action"] is not None and st["response"] is not None:
            lat = (st["response"] - st["action"]) / a.fps * 1000
            txt(f"latency = {st['response'] - st['action']} frames = {lat:.1f} ms", 112, (0, 255, 0))
        txt("a/d +-1  z/c +-10  x/v +-60 | k action  l response  u clear  t note  s save  n skip  p prev  q quit",
            show.shape[0] - 14, (200, 200, 200))
        cv2.imshow(win, show)

        key = cv2.waitKey(0) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("d"):
            frame += 1
        elif key == ord("a"):
            frame -= 1
        elif key == ord("c"):
            frame += 10
        elif key == ord("z"):
            frame -= 10
        elif key == ord("v"):
            frame += 60
        elif key == ord("x"):
            frame -= 60
        elif key == ord("k"):
            st["action"] = frame
        elif key == ord("l"):
            st["response"] = frame
        elif key == ord("u"):
            st["action"] = st["response"] = None
        elif key == ord("t"):
            st["note"] = input(f"Note for trial {t} (Enter to keep '{st['note']}'): ") or st["note"]
        elif key == ord("p"):
            ti = max(0, ti - 1)
        elif key == ord("n"):
            print(f"Skipped trial {t} (not saved). Pick a replacement at random and re-run with --trials.")
            if ti < len(trials) - 1:
                ti += 1
            else:
                break
        elif key == ord("s"):
            if st["action"] is None or st["response"] is None:
                print("Mark both the action (k) and the response (l) before saving.")
                continue
            diff = st["response"] - st["action"]
            if diff <= 0:
                print(f"Response must come after the action (got {diff} frames). Fix the marks.")
                continue
            save_row(a.csv, {
                "participant_id": a.participant, "mode": a.mode, "trial_id": t,
                "video_file": video_name, "fps": f"{a.fps:g}",
                "frame_action": st["action"], "frame_response": st["response"],
                "latency_ms": round(diff / a.fps * 1000, 1), "notes": st["note"],
            })
            print(f"Saved trial {t}: {diff} frames = {diff / a.fps * 1000:.1f} ms -> {a.csv}")
            if ti < len(trials) - 1:
                ti += 1
            else:
                print("All trials done.")
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
