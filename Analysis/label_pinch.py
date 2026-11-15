"""
Mark the "pinch fully closed" frame on gesture trials you already labelled for latency.

Why: latency_video.csv measures from the first frame where the fingers START closing to the first
screen response. This tool adds one more mark per trial, the first frame where thumb and index
finger TOUCH (pinch closed). Then, for each trial,
    pinch_ms          = (frame_pinch_closed - frame_action)   / fps * 1000   (time the hand takes to close)
    closed_to_resp_ms = (frame_response - frame_pinch_closed) / fps * 1000   (delay after the pinch is complete)
so you can say how much of the video latency is just the hand closing.

The action and response frames are read from latency_video.csv (you do not re-mark them). Results go to
pinch_closed.csv. Nothing in latency_video.csv is changed.

Install once:   pip install opencv-python pandas      (same as label_latency.py; keep both files in one folder)

Use (one video at a time, using the trial ids listed for that participant):
  python label_pinch.py --video P01_gesture.mp4 --participant P01 --trials 5 17

Keys (click the video window first):
  d / a   next / previous frame       c / z   +10 / -10 frames       v / x   +60 / -60 frames
  m       mark PINCH CLOSED frame (first frame where thumb and index fingertip touch)
  u       clear the mark              t   type a note
  s       SAVE this trial and go to the next      p   previous trial      q   quit
The window opens at the trial's action frame. The action and response frames are shown for reference.
"""
import argparse
import csv
import os
import sys

from label_latency import Video  # reuses the frame reader

OUT_COLUMNS = ["participant_id", "mode", "trial_id", "video_file", "fps", "frame_action",
               "frame_pinch_closed", "frame_response", "pinch_ms", "closed_to_resp_ms", "notes"]


def load_latency_rows(path, participant):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return {int(r["trial_id"]): r for r in rows
            if r["participant_id"] == participant and r["mode"] == "gesture"}


def save_row(path, row):
    rows = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    key = (row["participant_id"], row["mode"], str(row["trial_id"]))
    rows = [r for r in rows if (r["participant_id"], r["mode"], r["trial_id"]) != key]
    rows.append({c: row.get(c, "") for c in OUT_COLUMNS})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--participant", required=True)
    ap.add_argument("--trials", nargs="+", type=int, required=True)
    ap.add_argument("--latency-csv", default="latency_video.csv")
    ap.add_argument("--csv", default="pinch_closed.csv")
    ap.add_argument("--width", type=int, default=1280)
    a = ap.parse_args()

    known = load_latency_rows(a.latency_csv, a.participant)
    missing = [t for t in a.trials if t not in known]
    if missing:
        sys.exit(f"Trials {missing} are not gesture rows for {a.participant} in {a.latency_csv}.")

    import cv2
    vid = Video(a.video)
    video_name = os.path.basename(a.video)
    state = {t: {"closed": None, "note": ""} for t in a.trials}
    ti = 0
    frame = int(known[a.trials[0]]["frame_action"])
    jump = True
    win = "label_pinch"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while True:
        t = a.trials[ti]
        row = known[t]
        fa, fr, fps = int(row["frame_action"]), int(row["frame_response"]), float(row["fps"])
        if jump:
            frame = fa
            jump = False
        st = state[t]
        img, frame = vid.get(frame)
        h, w = img.shape[:2]
        scale = a.width / w
        show = cv2.resize(img, (a.width, int(h * scale))) if scale != 1 else img.copy()

        def txt(s, y, color=(255, 255, 255)):
            cv2.putText(show, s, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(show, s, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

        txt(f"{a.participant} gesture trial {t}  ({ti + 1}/{len(a.trials)})", 28)
        txt(f"frame {frame}   action {fa}   response {fr}   pinch closed: {st['closed']}", 56,
            (0, 255, 0) if st["closed"] is not None else (0, 215, 255))
        if st["closed"] is not None:
            txt(f"hand closing = {(st['closed'] - fa) / fps * 1000:.1f} ms   "
                f"closed -> response = {(fr - st['closed']) / fps * 1000:.1f} ms", 84, (0, 255, 0))
        txt("a/d +-1  z/c +-10  x/v +-60 | m pinch closed  u clear  t note  s save  p prev  q quit",
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
        elif key == ord("m"):
            st["closed"] = frame
        elif key == ord("u"):
            st["closed"] = None
        elif key == ord("t"):
            st["note"] = input(f"Note for trial {t} (Enter to keep '{st['note']}'): ") or st["note"]
        elif key == ord("p"):
            ti = max(0, ti - 1)
            jump = True
        elif key == ord("s"):
            c = st["closed"]
            if c is None:
                print("Press m on the pinch-closed frame first.")
                continue
            if not (fa <= c <= fr):
                print(f"Pinch-closed frame must be between action ({fa}) and response ({fr}). Fix the mark.")
                continue
            save_row(a.csv, {
                "participant_id": a.participant, "mode": "gesture", "trial_id": t,
                "video_file": video_name, "fps": f"{fps:g}", "frame_action": fa,
                "frame_pinch_closed": c, "frame_response": fr,
                "pinch_ms": round((c - fa) / fps * 1000, 1),
                "closed_to_resp_ms": round((fr - c) / fps * 1000, 1), "notes": st["note"],
            })
            print(f"Saved trial {t}: closing {(c - fa) / fps * 1000:.1f} ms, "
                  f"closed -> response {(fr - c) / fps * 1000:.1f} ms -> {a.csv}")
            if ti < len(a.trials) - 1:
                ti += 1
                jump = True
            else:
                print("All trials done.")
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
