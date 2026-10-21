"""Đánh giá mô hình trên dữ liệu Gold mới: chia theo thời gian, so với baseline, có ablation.

Chạy:
  python make_metrics.py                       # nhãn "popular" = top 1% stars_day_30 (ngưỡng tính trên tập train)
  python make_metrics.py --top-pct 5           # đổi sang top 5%
  python make_metrics.py --min-stars 50        # hoặc nhãn cố định: stars_day_30 >= 50
  python make_metrics.py --save-models         # ghi đè reg_model.pkl, cls_model.pkl bằng mô hình train-only
  python make_metrics.py --no-ablation         # bỏ qua ablation cho nhanh

Kết quả: metrics.json (app.py đọc ở tab "Chất lượng mô hình" và dùng nhãn trong đó).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# pyrefly: ignore[missing-import]
import joblib
# pyrefly: ignore[missing-import]
import numpy as np
import pandas as pd
# pyrefly: ignore[missing-import]
from sklearn.ensemble import (HistGradientBoostingClassifier, HistGradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (average_precision_score, f1_score, mean_absolute_error, mean_squared_error,
                             precision_score, r2_score, recall_score, roc_auc_score)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
MODELS_DIR = ROOT_DIR / "models"
METRICS_DIR = ROOT_DIR / "metrics"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR.mkdir(parents=True, exist_ok=True)

FEATURES = ["stars_day_1", "stars_day_3", "stars_day_7", "forks_day_7", "star_growth_rate",
            "total_pushes_7d", "total_commits_7d", "issues_opened_7d", "issues_closed_7d", "pr_opened_7d",
            "unique_contributors_7d", "unique_stargazers_7d", "desc_length", "has_trending_keywords"]
# unique_stargazers_7d gần như trùng stars_day_7 nên xếp chung nhóm "Lan tỏa sớm".
GROUPS = {
    "Lan tỏa sớm": ["stars_day_1", "stars_day_3", "stars_day_7", "forks_day_7", "star_growth_rate", "unique_stargazers_7d"],
    "Phát triển mã": ["total_pushes_7d", "total_commits_7d", "unique_contributors_7d"],
    "Cộng đồng": ["issues_opened_7d", "issues_closed_7d", "pr_opened_7d"],
    "Mô tả": ["desc_length", "has_trending_keywords"],
}

ap = argparse.ArgumentParser()
ap.add_argument("--top-pct", type=float, default=1.0)
ap.add_argument("--min-stars", type=int, default=None)
ap.add_argument("--save-models", action="store_true")
ap.add_argument("--no-ablation", action="store_true")
args = ap.parse_args()

data_file = DATA_DIR / "gold_data_local.csv"
if not data_file.exists():
    data_file = ROOT_DIR / "gold_data_local.csv"
df = pd.read_csv(data_file)
missing = [c for c in FEATURES + ["stars_day_30", "created_at"] if c not in df.columns]
if missing:
    raise SystemExit(f"Thiếu cột trong gold_data_local.csv: {missing}. Hãy dùng CSV xuất từ notebook ETL v2.")
df["created_at"] = pd.to_datetime(df["created_at"])
df = df.sort_values("created_at").reset_index(drop=True)
df["log_stars_30"] = np.log1p(df["stars_day_30"])

# --- Chia theo thời gian: 70% repo tạo sớm để train, 30% tạo muộn để test; 20% cuối của train làm validation
cut = int(len(df) * 0.7)
train, test = df.iloc[:cut].copy(), df.iloc[cut:].copy()
vcut = int(len(train) * 0.8)
fit, val = train.iloc[:vcut].copy(), train.iloc[vcut:].copy()
split = "theo thời gian tạo repo: 70% sớm nhất để train, 30% muộn nhất để test; ngưỡng chọn trên 20% cuối của train"

# --- Nhãn (ngưỡng tính trên train rồi áp dụng cho mọi tập, không nhìn test)
if args.min_stars is not None:
    thr, definition = args.min_stars, f"stars_day_30 >= {args.min_stars}"
else:
    thr = max(1, int(np.ceil(np.quantile(train["stars_day_30"], 1 - args.top_pct / 100))))
    definition = f"top {args.top_pct:g}% stars_day_30 trong tập train (tương đương >= {thr} stars)"
for part in (train, fit, val, test):
    part["y"] = (part["stars_day_30"] >= thr).astype(int)
print(f"Nhãn: {definition}")
print(f"Tỷ lệ dương: train {train.y.mean() * 100:.3f}% | test {test.y.mean() * 100:.3f}% ({int(test.y.sum()):,} repo)")
if test.y.sum() < 200:
    print("CẢNH BÁO: dưới 200 repo dương ở tập test, các chỉ số sẽ nhiễu. Hãy hạ ngưỡng (ví dụ --top-pct 5).")


def X(part, cols=FEATURES):
    return part[cols].fillna(0).astype("float32")


def reg_metrics(y, p):
    return {"RMSE": float(np.sqrt(mean_squared_error(y, p))), "MAE": float(mean_absolute_error(y, p)),
            "R2": float(r2_score(y, p)), "Spearman": float(pd.Series(np.asarray(y)).corr(pd.Series(p), method="spearman"))}


def best_threshold(y, score):
    cands = np.unique(np.quantile(score, np.linspace(0.5, 0.9995, 200)))
    return float(max(cands, key=lambda t: f1_score(y, (score >= t).astype(int), zero_division=0)))


def cls_metrics(y, score, t):
    pred = (score >= t).astype(int)
    return {"Precision": float(precision_score(y, pred, zero_division=0)), "Recall": float(recall_score(y, pred, zero_division=0)),
            "F1": float(f1_score(y, pred, zero_division=0)), "ROC-AUC": float(roc_auc_score(y, score)),
            "PR-AUC": float(average_precision_score(y, score))}


def make_rf_reg():
    ms = min(1.0, 300_000 / len(train))
    return RandomForestRegressor(n_estimators=150, min_samples_leaf=3, max_samples=ms, n_jobs=-1, random_state=42)


def make_rf_cls():
    ms = min(1.0, 300_000 / len(train))
    return RandomForestClassifier(n_estimators=150, min_samples_leaf=3, max_samples=ms, n_jobs=-1,
                                  class_weight="balanced_subsample", random_state=42)


# ---------------- Hồi quy
base_reg = LinearRegression().fit(np.log1p(train[["stars_day_7"]]), train["log_stars_30"])
rf_reg = make_rf_reg().fit(X(train), train["log_stars_30"])
hgb_reg = HistGradientBoostingRegressor(max_iter=200, random_state=42).fit(X(train), train["log_stars_30"])
regression = {
    "Baseline (chỉ stars ngày 7)": reg_metrics(test["log_stars_30"], base_reg.predict(np.log1p(test[["stars_day_7"]]))),
    "Random Forest": reg_metrics(test["log_stars_30"], rf_reg.predict(X(test))),
    "Gradient Boosting": reg_metrics(test["log_stars_30"], hgb_reg.predict(X(test))),
}

# ---------------- Phân loại: chọn ngưỡng trên validation, đánh giá trên test
t_base = best_threshold(val["y"], val["stars_day_7"])
classification = {f"Baseline (stars ngày 7 >= {t_base:g})": cls_metrics(test["y"], test["stars_day_7"], t_base)}
factories = {"Random Forest": make_rf_cls,
             "Gradient Boosting": lambda: HistGradientBoostingClassifier(max_iter=200, class_weight="balanced", random_state=42)}
fitted, val_pr = {}, {}
for name, make in factories.items():
    m_val = make().fit(X(fit), fit["y"])
    s_val = m_val.predict_proba(X(val))[:, 1]
    t = best_threshold(val["y"], s_val)
    val_pr[name] = average_precision_score(val["y"], s_val)
    m = make().fit(X(train), train["y"])
    fitted[name] = m
    classification[name] = cls_metrics(test["y"], m.predict_proba(X(test))[:, 1], t)
best_cls = max(val_pr, key=val_pr.get)
print(f"Mô hình phân loại tốt nhất trên validation: {best_cls}")

# ---------------- Ablation (Gradient Boosting, 3 lần chạy)
ablation = {}
if not args.no_ablation:
    variants = {"Đầy đủ": FEATURES} | {f"Bỏ nhóm {g}": [f for f in FEATURES if f not in cols] for g, cols in GROUPS.items()}
    for vname, cols in variants.items():
        r2s, prs = [], []
        for seed in (0, 1, 2):
            r = HistGradientBoostingRegressor(max_iter=150, random_state=seed).fit(X(train, cols), train["log_stars_30"])
            r2s.append(r2_score(test["log_stars_30"], r.predict(X(test, cols))))
            c = HistGradientBoostingClassifier(max_iter=150, class_weight="balanced", random_state=seed).fit(X(train, cols), train["y"])
            prs.append(average_precision_score(test["y"], c.predict_proba(X(test, cols))[:, 1]))
        ablation[vname] = {"R2": float(np.mean(r2s)), "R2 std": float(np.std(r2s)),
                           "PR-AUC": float(np.mean(prs)), "PR-AUC std": float(np.std(prs))}
        print(f"  ablation {vname}: R2={np.mean(r2s):.3f}  PR-AUC={np.mean(prs):.3f}")

out = {"split": split, "n_train": int(len(train)), "n_test": int(len(test)),
       "positive_rate_train": float(train.y.mean()), "positive_rate_test": float(test.y.mean()),
       "n_pos_test": int(test.y.sum()),
       "label": {"name": "Popular", "threshold_stars": int(thr), "definition": definition},
       "regression": regression, "classification": classification}
if ablation:
    out["ablation"] = ablation
(METRICS_DIR / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("regression", "classification")}, ensure_ascii=False, indent=2))

if args.save_models:
    joblib.dump(rf_reg, MODELS_DIR / "reg_model.pkl")
    joblib.dump(fitted[best_cls], MODELS_DIR / "cls_model.pkl")
    print(f"\nĐã lưu {MODELS_DIR / 'reg_model.pkl'} (Random Forest) và {MODELS_DIR / 'cls_model.pkl'} ({best_cls}), huấn luyện trên tập train.")

if classification[best_cls]["ROC-AUC"] > 0.98:
    print("\nLƯU Ý: ROC-AUC rất cao. Kiểm tra rò rỉ: nhãn có suy ra trực tiếp từ stars_day_7 / unique_stargazers_7d không?")
