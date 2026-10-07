#!/usr/bin/env python3
"""
Тест калибровки оценщика токенов (этап 4 плана
wiki/concepts/context_memory_research.md): EMA-коэффициент k per-model,
сходимость, защита от нуля/выбросов, персист в performance.log и восстановление.

Запуск: venv/bin/python -u tests/test_token_calibration.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import textual_integration as ti  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def reset_state():
    ti._token_k_state["by_model"].clear()
    ti._token_k_state["current"] = 1.0


def main() -> int:
    reset_state()
    msgs = [{"role": "user", "content": "x" * 4000}]  # raw-оценка = 1000+8

    # 1) сходимость EMA к истинному k=2.0
    ks = []
    for _ in range(30):
        k = ti.calibrate_token_estimator("m1", 2016, msgs)  # истинный k ≈ 2.0
        ks.append(k)
    check("converges_to_true_k", abs(ks[-1] - 2.0) < 0.05, str(round(ks[-1], 3)))
    check("monotone_rise", all(b > a for a, b in zip(ks, ks[1:])), str([round(x, 2) for x in ks[:5]]))

    # 2) защита от нуля и отсутствия данных — k не меняется, исключений нет
    before = ti._token_k_state["by_model"]["m1"]
    check("zero_metrics_skipped", ti.calibrate_token_estimator("m1", 0, msgs) is None)
    check("empty_messages_skipped", ti.calibrate_token_estimator("m1", 100, []) is None)
    check("no_model_skipped", ti.calibrate_token_estimator("", 100, msgs) is None)
    check("state_untouched", ti._token_k_state["by_model"]["m1"] == before)

    # 3) выброс за пределами 0.2–5.0 игнорируется
    reset_state()
    check("outlier_clamped", ti.calibrate_token_estimator("m2", 10 ** 9, msgs) is None)
    check("outlier_low_clamped", ti.calibrate_token_estimator("m2", 1, [{"role": "user", "content": "x" * 40000}]) is None)

    # 4) _estimate_tokens масштабируется текущим k
    reset_state()
    base = ti._estimate_tokens("y" * 4000)
    ti.calibrate_token_estimator("m3", 2008, msgs)  # k ≈ 1.3 после одного шага
    scaled = ti._estimate_tokens("y" * 4000)
    check("estimate_scaled", scaled > base, f"{scaled} vs {base}")
    reset_state()
    check("reset_restores_base", ti._estimate_tokens("y" * 4000) == base)

    # 5) per-model: калибровка m4 не трогает m5
    reset_state()
    ti.calibrate_token_estimator("m4", 2016, msgs)
    k_m4 = ti._token_k_state["by_model"]["m4"]
    ti.calibrate_token_estimator("m5", 504, msgs)
    check("per_model_isolated", ti._token_k_state["by_model"]["m4"] == k_m4)

    # 6) персист и восстановление
    reset_state()
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "performance.log")
        ti.calibrate_token_estimator("m6", 2016, msgs, persist_path=path)
        k_saved = ti._token_k_state["by_model"]["m6"]
        # мусорная строка и запись другой модели не мешают
        with open(path, "a", encoding="utf-8") as f:
            f.write("не json\n")
            f.write(json.dumps({"type": "token_calibration", "model": "other", "k": 3.0}) + "\n")
        reset_state()
        k_restored = ti.restore_token_calibration(path, "m6")
        check("persist_and_restore", k_restored is not None and abs(k_restored - k_saved) < 1e-6,
              f"{k_restored} vs {k_saved}")
        check("restore_missing_file_none", ti.restore_token_calibration(os.path.join(td, "nope.log"), "m6") is None)
        check("restore_unknown_model_none", ti.restore_token_calibration(path, "unknown") is None)

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ TOKEN CALIBRATION ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
