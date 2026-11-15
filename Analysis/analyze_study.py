#!/usr/bin/env python3
"""
AetherGrid study analysis: touch vs gesture, one row per participant and mode.

Usage (typical, real study):
  python analyze_study.py --device P01_device_metrics.csv P02_device_metrics.csv ... \
      --video latency_video.csv --observer observer_labels.csv \
      --surveys surveys.csv --participants participants.csv --out results

Testing on a dry-run file (participant_id empty, one participant):
  python analyze_study.py --device device_metrics.csv --fill-participant P00 \
      --exclude EXAMPLE --out dryrun_results

Design decisions (state these in the paper):
  * Unit of analysis is the participant: per-participant medians (or rates) per mode,
    compared touch vs gesture with a Wilcoxon signed-rank test, plus the median/mean
    paired difference, a bootstrap 95% CI, and the matched-pairs rank-biserial effect size.
  * Accuracy is FIRST-ATTEMPT accuracy. Retries are reported separately.
  * Selection time is measured on correct first attempts only.
  * In-app input latency is NOT compared across modes (different start points).
    Cross-mode latency comes from the 120 fps video (latency_video.csv).
  * Observer labels: false negatives / false positives per trial; 'unclear' trials excluded.
  * Results are exploratory (pilot). No multiple-comparison correction is applied.
"""
import argparse
import fnmatch
import glob
import os
import sys

import warnings

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

warnings.filterwarnings("ignore", category=RuntimeWarning)
MIN_N = 3            # minimum participants with both modes to run a paired test
KEY = ["participant_id", "mode", "trial_id"]
LOG = []


def log(msg=""):
    print(msg)
    LOG.append(str(msg))


def read_csv_any(path, **kw):
    """Read UTF-8, UTF-8 with BOM, or UTF-16 CSV files."""
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return pd.read_csv(path, encoding="latin-1", **kw)


def load_many(patterns, **kw):
    files = []
    for p in patterns:
        files.extend(sorted(glob.glob(p)) or [p])
    frames = []
    for f in files:
        d = read_csv_any(f, **kw)
        d["source_file"] = os.path.basename(f)
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def excluded(pid, patterns):
    return any(fnmatch.fnmatchcase(str(pid), p) for p in patterns)


def to_num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")


def tobool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def p95(s):
    s = pd.Series(s).dropna()
    return float(s.quantile(0.95)) if len(s) else np.nan


def show(df, title):
    log(f"\n=== {title} ===")
    log(df.round(2).to_string() if len(df) else "(empty)")


# ------------------------------------------------------------------ device_metrics
def prepare_device(dev, args):
    dev = dev.copy()
    for c in ("participant_id", "mode", "trial_id", "event", "run_label"):
        if c not in dev.columns:
            sys.exit(f"device_metrics is missing required column '{c}'")
    if dev["participant_id"].isna().any():
        if args.fill_participant:
            dev["participant_id"] = dev["participant_id"].fillna(args.fill_participant)
            log(f"NOTE: empty participant_id filled with '{args.fill_participant}' (testing only)")
        else:
            sys.exit("participant_id is empty on some/all rows. Set it in the app, "
                     "or use --fill-participant P00 to test on a dry-run file.")
    dev["participant_id"] = dev["participant_id"].astype(str)
    dev["mode"] = dev["mode"].astype(str).str.lower().str.strip()
    to_num(dev, ["trial_id", "t_elapsed_us", "t_prompt_us", "correct", "selection_time_ms",
                 "input_latency_ms", "frame_ms", "build_ms", "raster_ms", "inference_ms",
                 "camera_to_cursor_ms", "attempt_number"])   # level_id may be text (multiples_of_3)
    before = dev["participant_id"].nunique()
    dev = dev[~dev["participant_id"].map(lambda x: excluded(x, args.exclude))]
    log(f"Participants: {before} found, {dev['participant_id'].nunique()} kept "
        f"(excluded patterns: {args.exclude})")
    if "is_practice" in dev.columns:
        n = int(tobool(dev["is_practice"]).sum())
        dev = dev[~tobool(dev["is_practice"])]
        log(f"Practice rows removed via is_practice: {n}")
    else:
        log("WARN: no 'is_practice' column. Practice trials are NOT removed unless you ran them "
            "under an excluded ID (e.g. P03_practice).")
    return dev


def build_trials(dev, backtrack_as_error=False):
    # trial_id restarts in every mode file (and run_label is the same in both), so the trial key
    # must include the mode or touch and gesture trials of one participant get merged.
    keys = ["participant_id", "run_label", "mode", "trial_id"]
    prm = (dev[dev["event"] == "prompt"].sort_values("t_elapsed_us")
           .drop_duplicates(keys)[keys + ["t_elapsed_us"]
                                  + (["level_id"] if "level_id" in dev.columns else [])]
           .rename(columns={"t_elapsed_us": "t_prompt"}))
    sel = dev[dev["event"] == "selection"].sort_values("t_elapsed_us")
    grp = sel.groupby(keys)
    want = ["correct", "outcome", "selection_time_ms", "input_latency_ms", "trigger_type"]
    first = grp.first()[[c for c in want if c in sel.columns]]
    for c in want:
        if c not in first.columns:
            first[c] = np.nan
    first = first.rename(columns={"correct": "correct_first",
                                  "outcome": "outcome_first", "selection_time_ms": "sel_time_first",
                                  "input_latency_ms": "input_latency_first"})
    extra = pd.DataFrame({"n_attempts": grp.size(), "any_correct": grp["correct"].max()})
    tr = prm.merge(first.reset_index(), on=keys, how="outer").merge(
        extra.reset_index(), on=keys, how="left")

    unanswered = tr["correct_first"].isna() & tr["outcome_first"].isna()
    if unanswered.any():
        log(f"WARN: {int(unanswered.sum())} prompt(s) with no selection row were dropped "
            f"(session ended early, or timeouts are not logged as rows).")
    tr = tr[~unanswered].copy()

    tr["first_correct"] = np.where(tr["correct_first"].notna(), tr["correct_first"],
                                   (tr["outcome_first"] == "hit").astype(float))
    tr["backtrack"] = (tr["outcome_first"] == "backtracked").astype(float)
    if tr["backtrack"].sum():
        if backtrack_as_error:
            tr.loc[tr["backtrack"] == 1, "first_correct"] = 0.0
            log(f"NOTE: {int(tr['backtrack'].sum())} 'backtracked' first attempt(s) counted as errors.")
        else:
            tr.loc[tr["backtrack"] == 1, "first_correct"] = np.nan
            log(f"NOTE: {int(tr['backtrack'].sum())} 'backtracked' first attempt(s) excluded from accuracy and "
                f"selection time (reported as backtrack_rate). Use --backtrack-as-error to count them as errors.")
    tr["timeout"] = (tr["outcome_first"] == "timeout").astype(float)
    tr["sel_time_ok"] = np.where(tr["first_correct"] == 1, tr["sel_time_first"], np.nan)

    # A 'backtracked' trial is the recovery move after a wrong turn. The wrong turn itself is the
    # PREVIOUS trial (logged as a legal move), so mark it as a path error.
    tr = tr.sort_values(["participant_id", "run_label", "mode", "trial_id"]).reset_index(drop=True)
    next_back = tr.groupby(["participant_id", "run_label", "mode"])["backtrack"].shift(-1)
    tr["path_error"] = np.where(tr["backtrack"] == 1, np.nan, (next_back == 1).astype(float))
    tr["path_correct"] = np.where(tr["first_correct"].isna(), np.nan,
                                  np.where((tr["first_correct"] == 1) & (tr["path_error"] == 0), 1.0, 0.0))

    dup = tr.groupby(["participant_id", "mode", "trial_id"]).size()
    if (dup > 1).any():
        log("WARN: (participant_id, mode, trial_id) is not unique. Manual files cannot be "
            "joined reliably. Use a trial_id that is unique within each participant and mode.")
    return tr


# ------------------------------------------------------------------ observer / video / surveys
def cohen_kappa(a, b):
    a, b = np.asarray(a), np.asarray(b)
    po = np.mean(a == b)
    cats = np.union1d(a, b)
    pe = sum(np.mean(a == c) * np.mean(b == c) for c in cats)
    return np.nan if pe == 1 else (po - pe) / (1 - pe)


def load_observer(path, args, universe=None):
    ob = read_csv_any(path)
    ob = ob[~ob["participant_id"].map(lambda x: excluded(x, args.exclude))].copy()
    ob["mode"] = ob["mode"].astype(str).str.lower().str.strip()
    to_num(ob, ["trial_id", "false_negative", "false_positive", "unclear"])
    if "unclear" not in ob.columns:
        ob["unclear"] = 0
    if "rater" in ob.columns and ob["rater"].nunique() > 1:
        r = sorted(ob["rater"].dropna().unique())
        a = ob[ob["rater"] == args.primary_rater]
        for other in [x for x in r if x != args.primary_rater]:
            b = ob[ob["rater"] == other]
            # Rows only list trials where an error was seen. Agreement needs the trials the
            # second rater REVIEWED (including the ones with no error), otherwise it is
            # computed on flagged trials only and is meaningless.
            if getattr(args, "rater2_sample", None) or getattr(args, "rater2_rows_are_sample", False):
                if getattr(args, "rater2_sample", None):
                    reviewed = read_csv_any(args.rater2_sample)[KEY].copy()
                    src = args.rater2_sample
                else:
                    reviewed = b[KEY].copy()      # every row, including all-zero rows = a reviewed trial
                    src = f"the {other} rows"
                reviewed["mode"] = reviewed["mode"].astype(str).str.lower().str.strip()
                to_num(reviewed, ["trial_id"])
                reviewed = reviewed.drop_duplicates(KEY)
                if universe is not None:
                    ok = reviewed.merge(universe[KEY].drop_duplicates(), on=KEY, how="inner")
                    if len(ok) < len(reviewed):
                        gone = reviewed.merge(ok, on=KEY, how="left", indicator=True)
                        gone = gone[gone["_merge"] == "left_only"][KEY]
                        log(f"NOTE: {len(gone)} reviewed trial(s) are not real trials in the game logs and "
                            f"were dropped from agreement: "
                            + ", ".join(f"{r.participant_id}/{r['mode']}/{int(r.trial_id)}" for _, r in gone.iterrows()))
                    reviewed = ok
                basis = f"{len(reviewed)} trials ({src})"
            elif getattr(args, "rater2_reviewed_all", False) and universe is not None:
                reviewed = universe[KEY].drop_duplicates()
                basis = "all trials"
            else:
                log(f"Inter-rater ({args.primary_rater} vs {other}): NOT computed. Rows list only the "
                    f"trials where an error was seen, so the script cannot tell which trials {other} "
                    f"reviewed. Give --rater2-sample <csv of reviewed trials> or --rater2-reviewed-all.")
                continue
            lab_cols = ["false_negative", "false_positive", "unclear"]
            m = (reviewed.merge(a[KEY + lab_cols], on=KEY, how="left")
                         .merge(b[KEY + lab_cols], on=KEY, how="left", suffixes=("_1", "_2")))
            m[[f"{c}_{i}" for c in lab_cols for i in (1, 2)]] = \
                m[[f"{c}_{i}" for c in lab_cols for i in (1, 2)]].fillna(0)
            uncl = (m["unclear_1"] > 0) | (m["unclear_2"] > 0)
            mm = m[~uncl]
            log(f"Inter-rater ({args.primary_rater} vs {other}): reviewed by {other}: {basis}; "
                f"{int(uncl.sum())} excluded (unclear by either rater), n={len(mm)} used.")
            for lab in ("false_negative", "false_positive"):
                x1, x2 = mm[f"{lab}_1"], mm[f"{lab}_2"]
                k = cohen_kappa(x1, x2)
                agree = 100 * np.mean(x1 == x2) if len(mm) else np.nan
                both = int(((x1 > 0) & (x2 > 0)).sum())
                log(f"  {lab}: {args.primary_rater} flagged {int((x1 > 0).sum())}, {other} flagged "
                    f"{int((x2 > 0).sum())}, both {both}; agreement={agree:.0f}%, Cohen's kappa={k:.2f}")
        ob = a
    return ob[KEY + ["false_negative", "false_positive", "unclear"]].drop_duplicates(KEY)


def load_video(path, args):
    v = read_csv_any(path)
    v = v[~v["participant_id"].map(lambda x: excluded(x, args.exclude))].copy()
    v["mode"] = v["mode"].astype(str).str.lower().str.strip()
    to_num(v, ["trial_id", "fps", "frame_action", "frame_response"])
    v["video_latency_ms"] = (v["frame_response"] - v["frame_action"]) / v["fps"] * 1000.0
    bad = v[(v["video_latency_ms"] <= 0) | v["video_latency_ms"].isna()]
    if len(bad):
        log(f"WARN: {len(bad)} video row(s) with missing/non-positive latency were dropped.")
        v = v.drop(bad.index)
    odd = v[(v["fps"] < 60) | (v["fps"] > 480)]
    if len(odd):
        log(f"WARN: {len(odd)} video row(s) have an unusual fps (check the real recorded fps).")
    return v


def score_surveys(path, args):
    s = read_csv_any(path)
    s = s[~s["participant_id"].map(lambda x: excluded(x, args.exclude))].copy()
    s["mode"] = s["mode"].astype(str).str.lower().str.strip()
    sus_cols = [f"sus_{i}" for i in range(1, 11)]
    if all(c in s.columns for c in sus_cols):
        to_num(s, sus_cols)
        odd = sum(s[f"sus_{i}"] - 1 for i in (1, 3, 5, 7, 9))
        even = sum(5 - s[f"sus_{i}"] for i in (2, 4, 6, 8, 10))
        s["sus"] = (odd + even) * 2.5
    elif "sus_score" in s.columns:
        s["sus"] = pd.to_numeric(s["sus_score"], errors="coerce")
    tlx = ["tlx_mental", "tlx_physical", "tlx_temporal", "tlx_performance", "tlx_effort", "tlx_frustration"]
    if all(c in s.columns for c in tlx):
        to_num(s, tlx)
        s["tlx_raw"] = s[tlx].mean(axis=1)      # raw (unweighted) NASA-TLX
    to_num(s, ["borg_cr10"])
    cols = [c for c in ("sus", "tlx_raw", "borg_cr10") if c in s.columns]
    return s.groupby(["participant_id", "mode"])[cols].mean().reset_index()


# ------------------------------------------------------------------ per participant x mode
def system_metrics(dev, budget_ms):
    w = (dev[dev["event"].isin(["prompt", "selection"])]
         .groupby(["participant_id", "mode"])["t_elapsed_us"].agg(t0="min", t1="max"))
    ui = dev[dev["event"] == "ui_frame"].merge(w, left_on=["participant_id", "mode"],
                                                right_index=True, how="inner")
    ui = ui[(ui["t_elapsed_us"] >= ui["t0"]) & (ui["t_elapsed_us"] <= ui["t1"])]
    g = ui.groupby(["participant_id", "mode"])
    fm = pd.DataFrame({
        "ui_frames": g.size(),
        "frame_median_ms": g["frame_ms"].median(),
        "frame_p95_ms": g["frame_ms"].apply(p95),
        "over_budget_pct": g["frame_ms"].apply(lambda s: 100 * (s.dropna() > budget_ms).mean()),
        "build_median_ms": g["build_ms"].median(),
        "raster_median_ms": g["raster_ms"].median(),
    })
    secs = (w["t1"] - w["t0"]) / 1e6
    fm["ui_frames_per_s_logged"] = fm["ui_frames"] / secs.reindex(fm.index)

    vis = dev[dev["event"] == "vision_frame"].merge(w, left_on=["participant_id", "mode"],
                                                    right_index=True, how="inner")
    vis = vis[(vis["t_elapsed_us"] >= vis["t0"]) & (vis["t_elapsed_us"] <= vis["t1"])].copy()
    vm = pd.DataFrame()
    if len(vis):
        vis["hand"] = tobool(vis["hand_detected"]) if "hand_detected" in vis else False
        vg = vis.groupby(["participant_id", "mode"])
        vm = pd.DataFrame({
            "inference_median_ms": vg["inference_ms"].median(),
            "inference_p95_ms": vg["inference_ms"].apply(p95),
            "cam_to_cursor_median_ms": vg["camera_to_cursor_ms"].median(),
            "hand_detected_pct": vg["hand"].apply(lambda s: 100 * s.mean()),
        })
    return fm, vm, ui


def trial_metrics(tr):
    g = tr.groupby(["participant_id", "mode"])
    out = pd.DataFrame({
        "n_trials": g.size(),
        "first_attempt_acc": g["first_correct"].mean(),
        "path_accuracy": g["path_correct"].mean(),
        "retry_rate": g["n_attempts"].apply(lambda s: (s.dropna() > 1).mean()),
        "timeout_rate": g["timeout"].mean(),
        "backtrack_rate": g["backtrack"].mean(),
        "sel_time_median_ms": g["sel_time_ok"].median(),
        "input_latency_median_ms": g["input_latency_first"].median(),
        "input_latency_blank_pct": g["input_latency_first"].apply(lambda s: 100 * s.isna().mean()),
    })
    if "fn" in tr.columns:
        use = tr[tr["unclear"].fillna(0) != 1]
        gg = use.groupby(["participant_id", "mode"])
        out["fn_rate"] = gg["fn"].mean()
        out["fp_rate"] = gg["fp"].mean()
        out["unclear_trials"] = tr.groupby(["participant_id", "mode"])["unclear"].sum()
    return out


# ------------------------------------------------------------------ paired statistics
def paired_row(label, wide):
    a = wide["touch"].to_numpy(float)
    b = wide["gesture"].to_numpy(float)
    d = b - a
    n = len(d)
    row = {"metric": label, "n": n, "touch_median": np.median(a), "gesture_median": np.median(b),
           "median_diff_g_minus_t": np.median(d), "mean_diff_g_minus_t": d.mean(),
           "ci95_low": np.nan, "ci95_high": np.nan, "rank_biserial": np.nan, "wilcoxon_p": np.nan,
           "n_gesture_higher": int((d > 0).sum()), "n_touch_higher": int((d < 0).sum())}
    if n >= 2:
        boots = np.random.default_rng(0).choice(d, size=(10000, n), replace=True).mean(axis=1)
        row["ci95_low"], row["ci95_high"] = np.percentile(boots, [2.5, 97.5])
    nz = d[d != 0]
    if len(nz):
        ranks = stats.rankdata(np.abs(nz))
        wp, wm = ranks[nz > 0].sum(), ranks[nz < 0].sum()
        row["rank_biserial"] = (wp - wm) / (wp + wm)
    try:
        row["wilcoxon_p"] = float(stats.wilcoxon(a, b).pvalue)
    except ValueError:
        pass
    return row


def paired_plot(label, wide, path):
    fig, ax = plt.subplots(figsize=(3.6, 4))
    for _, r in wide.iterrows():
        ax.plot([0, 1], [r["touch"], r["gesture"]], "-o", color="0.6", lw=1, ms=4)
    ax.plot([0, 1], [wide["touch"].median(), wide["gesture"].median()], "-s",
            color="C3", lw=2.5, ms=8, label="median")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["touch", "gesture"])
    ax.set_xlim(-0.3, 1.3)
    ax.set_title(label, fontsize=9)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ------------------------------------------------------------------ main
TESTS = [
    ("sel_time_median_ms", "Selection time, correct first attempts (ms)"),
    ("first_attempt_acc", "First-attempt accuracy: valid tile (proportion)"),
    ("path_accuracy", "Path accuracy: valid tile and no wrong turn (proportion)"),
    ("fn_rate", "Observer-labeled false-negative rate"),
    ("fp_rate", "Observer-labeled false-positive rate"),
    ("video_latency_median_ms", "End-to-end latency, 120 fps video (ms)"),
    ("frame_median_ms", "UI frame time, median (ms)"),
    ("frame_p95_ms", "UI frame time, p95 (ms)"),
    ("over_budget_pct", "UI frames over budget (%)"),
    ("sus", "SUS (0-100, higher = better)"),
    ("tlx_raw", "NASA-TLX raw (0-100, higher = more workload)"),
    ("borg_cr10", "Borg CR10 arm fatigue (0-10)"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", nargs="+", required=True)
    ap.add_argument("--video")
    ap.add_argument("--observer")
    ap.add_argument("--surveys")
    ap.add_argument("--participants")
    ap.add_argument("--out", default="results")
    ap.add_argument("--exclude", nargs="*", default=["P00", "EXAMPLE", "*_practice"],
                    help="participant_id patterns to drop (fnmatch). Default drops dry-run/example/practice IDs.")
    ap.add_argument("--fill-participant", help="fill empty participant_id (dry-run testing only)")
    ap.add_argument("--budget-ms", type=float, default=16.7, help="frame budget for 'over budget' (default 16.7)")
    ap.add_argument("--primary-rater", default="rater1")
    ap.add_argument("--rater2-sample",
                    help="CSV (participant_id,mode,trial_id) of the trials the second rater reviewed, "
                         "including trials where they saw no error; needed for inter-rater agreement")
    ap.add_argument("--rater2-rows-are-sample", action="store_true",
                    help="every second-rater row, including all-zero rows, is a trial that rater reviewed")
    ap.add_argument("--rater2-reviewed-all", action="store_true",
                    help="the second rater reviewed every trial (use instead of --rater2-sample)")
    ap.add_argument("--unlabeled-as-missing", action="store_true",
                    help="trials with no observer row stay NaN instead of counting as 0/0")
    ap.add_argument("--backtrack-as-error", action="store_true",
                    help="count 'backtracked' first attempts as errors (default: exclude them from accuracy)")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    plots = os.path.join(args.out, "plots")
    os.makedirs(plots, exist_ok=True)

    dev = prepare_device(load_many(args.device, low_memory=False), args)
    if dev.empty:
        sys.exit("No device_metrics rows left after exclusions.")
    tr = build_trials(dev, args.backtrack_as_error)

    # observer labels
    if args.observer:
        ob = load_observer(args.observer, args, universe=tr)
        tr = tr.merge(ob.rename(columns={"false_negative": "fn", "false_positive": "fp"}),
                      on=KEY, how="left")
        miss = int(tr["fn"].isna().sum())
        if not args.unlabeled_as_missing:
            tr[["fn", "fp"]] = tr[["fn", "fp"]].fillna(0)
            tr["unclear"] = tr["unclear"].fillna(0)
            log(f"Observer labels: {miss} of {len(tr)} trials had no row and were counted as 0/0 "
                f"(no error observed). Use --unlabeled-as-missing to change.")
        else:
            log(f"Observer labels: {miss} of {len(tr)} trials unlabeled (left missing).")

    # video latency
    vid = None
    if args.video:
        vid = load_video(args.video, args)
        tr = tr.merge(vid[KEY + ["video_latency_ms"]].drop_duplicates(KEY), on=KEY, how="left")
        orphan = vid.merge(tr[KEY], on=KEY, how="left", indicator=True)
        n_orphan = int((orphan["_merge"] == "left_only").sum())
        if n_orphan:
            log(f"WARN: {n_orphan} video row(s) did not match any trial (check participant_id/mode/trial_id).")
        cnt = vid.groupby(["participant_id", "mode"]).size().unstack(fill_value=0)
        show(cnt, "Video-annotated trials per participant and mode")

    # per participant x mode table
    pm = trial_metrics(tr)
    fm, vm, ui = system_metrics(dev, args.budget_ms)
    if len(fm):
        pm = pm.join(fm, how="outer")
    if len(vm):
        pm = pm.join(vm, how="outer")
    if vid is not None:
        pm = pm.join(vid.groupby(["participant_id", "mode"])["video_latency_ms"]
                     .median().rename("video_latency_median_ms"), how="left")
    if args.surveys:
        sv = score_surveys(args.surveys, args).set_index(["participant_id", "mode"])
        pm = pm.join(sv, how="left")
    pm = pm.reset_index()

    # design checks
    both = pm.groupby("participant_id")["mode"].nunique()
    full = both[both == 2].index
    log(f"\nParticipants with both modes: {len(full)} of {pm['participant_id'].nunique()}")
    # t_elapsed_us restarts at 0 in every mode file, so order by wall-clock time when available.
    ev = dev[dev["event"].isin(["prompt", "selection"])].copy()
    if "timestamp_utc" in ev.columns and pd.to_datetime(ev["timestamp_utc"], errors="coerce", utc=True).notna().any():
        ev["_t"] = pd.to_datetime(ev["timestamp_utc"], errors="coerce", utc=True)
    else:
        ev["_t"] = ev["t_elapsed_us"]
    first_mode = ev.sort_values("_t").groupby("participant_id")["mode"].first()
    if len(first_mode):
        log("Order (first mode played): " + ", ".join(f"{k}={v}" for k, v in first_mode.value_counts().items())
            + "  (counterbalanced design expects equal counts)")
    if "level_id" in tr.columns and tr["level_id"].notna().any():
        lv = tr.groupby(["participant_id", "mode"])["level_id"].agg(lambda s: tuple(sorted(set(s.dropna()))))
        lvs = lv.unstack()
        if "touch" in lvs and "gesture" in lvs:
            diff = lvs[lvs["touch"] != lvs["gesture"]]
            if len(diff):
                log(f"WARN: touch and gesture used different levels for {list(diff.index)}")
            else:
                log("Levels played match between touch and gesture for every participant.")
    else:
        log("WARN: no level_id; cannot verify both modes used the same levels.")

    show(pm.set_index(["participant_id", "mode"]).T, "Per participant and mode")

    # descriptive-only block
    desc_cols = [c for c in ("input_latency_median_ms", "input_latency_blank_pct", "inference_median_ms",
                             "cam_to_cursor_median_ms", "hand_detected_pct", "ui_frames_per_s_logged",
                             "retry_rate", "timeout_rate", "backtrack_rate") if c in pm.columns]
    log("\nNote: input_latency_median_ms starts at different points in touch (pointer-up) and gesture "
        "(camera capture); it is reported descriptively and NOT tested across modes.")

    # paired tests
    rows = []
    for col, label in TESTS:
        if col not in pm.columns:
            continue
        wide = pm.pivot(index="participant_id", columns="mode", values=col)
        if not {"touch", "gesture"} <= set(wide.columns):
            continue
        wide = wide[["touch", "gesture"]].dropna()
        if len(wide) < MIN_N:
            log(f"Skipping '{label}': only {len(wide)} participant(s) with both modes (need >= {MIN_N}).")
            continue
        rows.append(paired_row(label, wide))
        if not args.no_plots:
            paired_plot(label, wide, os.path.join(plots, f"paired_{col}.png"))
    tests = pd.DataFrame(rows)
    if len(tests):
        show(tests.set_index("metric"), "Paired comparisons (gesture minus touch), per-participant values")
        n_min = int(tests["n"].min())
        n_txt = f"{n_min}" if n_min == int(tests["n"].max()) else f"{n_min}-{int(tests['n'].max())}"
        log(f"\nCaution: n = {n_txt} participants. Exploratory pilot; "
            f"report effect sizes and paired plots, not only p-values. With n=6 the smallest "
            f"possible two-sided exact Wilcoxon p is 0.031.")
    tests.to_csv(os.path.join(args.out, "paired_tests.csv"), index=False)

    # preference
    if args.participants:
        pt = read_csv_any(args.participants)
        pt = pt[~pt["participant_id"].map(lambda x: excluded(x, args.exclude))]
        if "preference" in pt.columns:
            show(pt["preference"].value_counts().to_frame("count"), "Stated preference")

    # distribution plots
    if not args.no_plots:
        if vid is not None and len(vid):
            fig, ax = plt.subplots(figsize=(4, 4))
            data = [vid.loc[vid["mode"] == m, "video_latency_ms"].dropna() for m in ("touch", "gesture")]
            ax.boxplot(data, tick_labels=["touch", "gesture"], showfliers=False)
            for i, d in enumerate(data, 1):
                ax.scatter(np.random.default_rng(1).normal(i, 0.05, len(d)), d, s=12, alpha=0.6)
            ax.set_ylabel("end-to-end latency (ms)")
            ax.set_title("Video latency, all annotated trials", fontsize=9)
            fig.tight_layout()
            fig.savefig(os.path.join(plots, "video_latency_distribution.png"), dpi=150)
            plt.close(fig)
        if len(ui):
            fig, ax = plt.subplots(figsize=(5, 4))
            for m, g in ui.groupby("mode"):
                x = np.sort(g["frame_ms"].dropna().to_numpy())
                if len(x):
                    ax.plot(x, np.arange(1, len(x) + 1) / len(x), label=m)
            ax.axvline(args.budget_ms, color="0.5", ls="--", lw=1)
            ax.set_xlabel("UI frame time (ms)")
            ax.set_ylabel("cumulative share of frames")
            ax.set_xlim(0, np.nanpercentile(ui["frame_ms"], 99.5))
            ax.legend()
            fig.tight_layout()
            fig.savefig(os.path.join(plots, "frame_time_ecdf.png"), dpi=150)
            plt.close(fig)

    tr.to_csv(os.path.join(args.out, "trial_level.csv"), index=False)
    pm.to_csv(os.path.join(args.out, "participant_mode_summary.csv"), index=False)
    with open(os.path.join(args.out, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    log(f"\nWrote results to: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
