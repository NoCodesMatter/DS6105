#!/usr/bin/env python3
"""Regenerate Task 3 and Task 4 tables and charts from raw timing CSVs (Lu Wenrui).

Task 3 input: Sun's baseline CSV, one row per run, with at least
    query_id, dataset_stage, transaction_count, run_number, runtime_ms
Task 4 input: output of analysis/index_experiment.py (or Sun's indexed runs) with
    index_config, query_id, run_number, runtime_ms   ('baseline' = no extra index)

Outputs (in --outdir):
    task3_summary.csv              mean / sd / min / max per query x stage
    task3_size_vs_runtime_Qn.png   one line chart per query (+ combined overview)
    task4_summary.csv              mean per query x index config, speed-up vs baseline
    task4_index_effect_Qn.png      bar chart per query (with / without each index)

Example:
    python analysis/plot_performance.py --task3 analysis/results/baseline_raw.csv \
        --task4 analysis/results/index_experiment_raw.csv --outdir report/figures
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

COLORS = ["#2a6fdb", "#e0703b", "#2e9e6b", "#b24bd1", "#c9a227", "#d64550", "#5c6b7a"]


def summarise(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    g = df.groupby(keys)["runtime_ms"]
    out = g.agg(runs="count", mean_ms="mean", sd_ms="std", min_ms="min", max_ms="max").reset_index()
    return out.round(3)


def task3(path: Path, outdir: Path) -> None:
    df = pd.read_csv(path)
    bad = df.groupby(["query_id", "dataset_stage"]).size()
    if (bad != 5).any():
        print("WARNING: not exactly 5 runs for:\n", bad[bad != 5])
    s = summarise(df, ["query_id", "dataset_stage", "transaction_count"])
    s = s.sort_values(["query_id", "transaction_count"])
    s.to_csv(outdir / "task3_summary.csv", index=False)

    fig_all, ax_all = plt.subplots(figsize=(8, 5))
    for i, (qid, d) in enumerate(s.groupby("query_id")):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.errorbar(d["transaction_count"], d["mean_ms"], yerr=d["sd_ms"].fillna(0),
                    marker="o", capsize=3, color=COLORS[i % len(COLORS)])
        ax.set_title(f"{qid}: database size vs runtime (mean of 5 runs)")
        ax.set_xlabel("Resale transactions loaded")
        ax.set_ylabel("Execution time (ms)")
        ax.grid(alpha=0.3)
        ax.ticklabel_format(axis="x", style="plain")
        fig.tight_layout()
        fig.savefig(outdir / f"task3_size_vs_runtime_{qid}.png", dpi=200)
        plt.close(fig)
        ax_all.plot(d["transaction_count"], d["mean_ms"], marker="o", label=qid,
                    color=COLORS[i % len(COLORS)])
    ax_all.set_title("Baseline runtime vs database size, Q1–Q6")
    ax_all.set_xlabel("Resale transactions loaded")
    ax_all.set_ylabel("Mean execution time (ms)")
    ax_all.grid(alpha=0.3)
    ax_all.legend()
    ax_all.ticklabel_format(axis="x", style="plain")
    fig_all.tight_layout()
    fig_all.savefig(outdir / "task3_size_vs_runtime_all.png", dpi=200)
    plt.close(fig_all)


def task4(path: Path, outdir: Path) -> None:
    df = pd.read_csv(path)
    s = summarise(df, ["query_id", "index_config"])
    base = s[s.index_config == "baseline"].set_index("query_id")["mean_ms"]
    s["baseline_ms"] = s["query_id"].map(base)
    s["speedup_x"] = (s["baseline_ms"] / s["mean_ms"]).round(2)
    s["change_pct"] = ((s["mean_ms"] - s["baseline_ms"]) / s["baseline_ms"] * 100).round(1)
    if "plan_uses_index" in df.columns:
        used = (df.groupby(["query_id", "index_config"])["plan_uses_index"]
                .first().fillna("").astype(str).reset_index())
        s = s.merge(used, on=["query_id", "index_config"], how="left")
    s.to_csv(outdir / "task4_summary.csv", index=False)

    order = ["baseline"] + [c for c in df["index_config"].unique() if c != "baseline"]
    for qid, d in s.groupby("query_id"):
        d = d.set_index("index_config").reindex(order).dropna(subset=["mean_ms"])
        fig, ax = plt.subplots(figsize=(7, 4.2))
        used = d["plan_uses_index"].fillna("").astype(str) if "plan_uses_index" in d else pd.Series("x", d.index)
        # Grey = baseline; dark blue = plan uses the index; light = index ignored by the planner
        colors = ["#8a94a3" if c == "baseline" else ("#2a6fdb" if used[c] else "#b9cdf2")
                  for c in d.index]
        sd = d["sd_ms"].fillna(0)
        ax.bar(range(len(d)), d["mean_ms"], yerr=sd, capsize=3, color=colors)
        ax.set_xticks(range(len(d)))
        ax.set_xticklabels(d.index, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel("Mean execution time (ms)")
        ax.set_title(f"{qid}: without vs with each index (largest database)")
        top = (d["mean_ms"] + sd).max()
        for x, (m, s_, pct) in enumerate(zip(d["mean_ms"], sd, d["change_pct"])):
            label = f"{m:.0f}" if x == 0 else f"{m:.0f}\n({pct:+.0f}%)"
            ax.text(x, m + s_ + top * 0.02, label, ha="center", va="bottom", fontsize=7)
        ax.set_ylim(0, top * 1.22)
        ax.text(0.99, 0.98, "dark = index used in plan, light = not used",
                transform=ax.transAxes, ha="right", va="top", fontsize=7, color="#555")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(outdir / f"task4_index_effect_{qid}.png", dpi=200)
        plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task3", type=Path)
    ap.add_argument("--task4", type=Path)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    if args.task3:
        task3(args.task3, args.outdir)
    if args.task4:
        task4(args.task4, args.outdir)


if __name__ == "__main__":
    main()
