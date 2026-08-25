#!/usr/bin/env python3
"""Fine-tuning 로그, 메모리 정리, 손실 그래프 유틸리티를 제공한다."""

import gc
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import torch
from transformers import TrainerCallback, TrainerControl, TrainerState, TrainingArguments


def setup_clean_logging() -> None:
    """HuggingFace / 관련 라이브러리의 verbose INFO 로그를 억제한다."""
    for lib in ("transformers", "datasets", "tokenizers", "accelerate", "peft",
                "filelock", "fsspec", "huggingface_hub"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def _empty_device_cache() -> None:
    """MPS/CUDA allocator가 캐시로 쥐고 있는 메모리를 OS로 회수한다."""
    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    elif torch.cuda.is_available():
        torch.cuda.empty_cache()


class MemoryCleanupCallback(TrainerCallback):
    """평가와 저장 후 장치 메모리 캐시를 비운다."""

    def on_evaluate(self, args: TrainingArguments, state: TrainerState,
                    control: TrainerControl, **kwargs):
        _empty_device_cache()

    def on_save(self, args: TrainingArguments, state: TrainerState,
                control: TrainerControl, **kwargs):
        _empty_device_cache()


# Epoch 손실 기록 콜백.

class EpochLossCallback(TrainerCallback):
    """Epoch별 학습·평가 손실을 출력하고 로그로 저장한다."""

    def __init__(self, agent_name: str, log_dir: Optional[Path] = None):
        self.agent_name = agent_name
        self.log_dir = Path(log_dir) if log_dir else None
        self._step_losses: list[float] = []
        self._current_epoch = 0
        self._lines: list[str] = []
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def on_log(self, args: TrainingArguments, state: TrainerState,
               control: TrainerControl, logs=None, **kwargs):
        if logs is None:
            return
        loss = logs.get("loss")
        if loss is not None:
            self._step_losses.append(float(loss))

    def on_epoch_end(self, args: TrainingArguments, state: TrainerState,
                     control: TrainerControl, **kwargs):
        self._current_epoch += 1
        total_epochs = int(args.num_train_epochs)

        avg_train = (sum(self._step_losses) / len(self._step_losses)
                     if self._step_losses else None)
        self._step_losses.clear()

        # 최근 평가 손실.
        eval_loss = None
        for entry in reversed(state.log_history):
            if "eval_loss" in entry:
                eval_loss = entry["eval_loss"]
                break

        parts = [f"[{self.agent_name}] Epoch {self._current_epoch:>2}/{total_epochs}"]
        if avg_train is not None:
            parts.append(f"train_loss={avg_train:.4f}")
        if eval_loss is not None:
            parts.append(f"eval_loss={eval_loss:.4f}")

        line = "  |  ".join(parts)
        print(line, flush=True)
        self._lines.append(line)

    def on_train_end(self, args: TrainingArguments, state: TrainerState,
                     control: TrainerControl, **kwargs):
        if self.log_dir is None:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Epoch 요약.
        summary_path = self.log_dir / f"{self.agent_name}_{self._timestamp}_epochs.log"
        summary_path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")

        # 전체 학습 로그.
        json_path = self.log_dir / f"{self.agent_name}_{self._timestamp}_log_history.json"
        json_path.write_text(
            json.dumps(state.log_history, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Epoch log   : {summary_path}", flush=True)
        print(f"Log history : {json_path}", flush=True)


# 손실 추세 그래프.

def plot_loss_curve(
    log_history: list[dict],
    output_path: Path,
    title: str = "Training Loss",
) -> None:
    """학습 로그의 train/eval 손실 추세를 이미지로 저장한다."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib이 없어 loss 그래프를 건너뜁니다.", flush=True)
        return

    train_steps, train_losses = [], []
    eval_steps,  eval_losses  = [], []

    for entry in log_history:
        step = entry.get("step", 0)
        # 평가 로그와 학습 로그를 분리한다.
        if "eval_loss" in entry:
            eval_steps.append(step)
            eval_losses.append(entry["eval_loss"])
        elif "loss" in entry:
            train_steps.append(step)
            train_losses.append(entry["loss"])

    if not train_losses and not eval_losses:
        print("log_history에 loss 정보가 없어 그래프를 건너뜁니다.", flush=True)
        return

    # 그래프 색상.
    BG      = "#0f1117"
    PANEL   = "#1a1d27"
    GRID    = "#2c2f3e"
    TEXT    = "#dde1f0"
    MUTED   = "#7a7f99"
    BLUE    = "#4f8ef7"
    RED     = "#ef5350"

    fig, ax = plt.subplots(figsize=(11, 5))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)

    if train_losses:
        ax.plot(train_steps, train_losses,
                color=BLUE, linewidth=1.5, alpha=0.85,
                label="Train Loss")
    if eval_losses:
        ax.plot(eval_steps, eval_losses,
                color=RED, linewidth=2.0,
                marker="o", markersize=5, zorder=5,
                label="Eval Loss")

    ax.set_xlabel("Step", color=MUTED, fontsize=11)
    ax.set_ylabel("Loss", color=MUTED, fontsize=11)
    ax.set_title(title, color=TEXT, fontsize=13, pad=12)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linestyle="--", alpha=0.6)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, fontsize=10)

    plt.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"Loss curve  : {output_path}", flush=True)
