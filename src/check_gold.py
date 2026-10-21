"""Kiểm tra nhanh bảng Gold mới trước khi huấn luyện.

Chạy:  python check_gold.py
In ra: (1) tính đúng đắn của dữ liệu, (2) các lựa chọn nhãn và số mẫu dương,
(3) độ mạnh của baseline, (4) gợi ý số liệu cho 3 kịch bản mẫu trong app.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT_DIR = Path(__file__).resolve().parent.parent
data_path = ROOT_DIR / "data" / "gold_data_local.csv"
if not data_path.exists():
    data_path = ROOT_DIR / "gold_data_local.csv"

df = pd.read_csv(data_path, parse_dates=["created_at"])
df = df.sort_values("created_at").reset_index(drop=True)
print(f"\n=== 1. Dữ liệu ===\nSố repo: {len(df):,} | tạo từ {df.created_at.min()} đến {df.created_at.max()}")

by_day = df.groupby(df.created_at.dt.date).agg(
    so_repo=("repo_id", "size"), stars7_tb=("stars_day_7", "mean"), stars30_tb=("stars_day_30", "mean"),
    pct_ge50=("stars_day_30", lambda s: (s >= 50).mean() * 100)).round(3)
print(by_day.to_string())
print("\nstars_30 < stars_7 (phải = 0):", int((df.stars_day_30 < df.stars_day_7).sum()))
print("unique_stargazers_7d == stars_day_7:", f"{(df.unique_stargazers_7d == df.stars_day_7).mean() * 100:.1f}% repo")
print("primary_language bị thiếu:", f"{df.primary_language.isna().mean() * 100:.1f}%")
print("has_trending_keywords = 1:", f"{df.has_trending_keywords.mean() * 100:.1f}%",
      "| desc_length = 0:", f"{(df.desc_length == 0).mean() * 100:.1f}%")

cut = int(len(df) * 0.7)
train, test = df.iloc[:cut], df.iloc[cut:]
print("\n=== 2. Lựa chọn nhãn (ngưỡng tính trên tập train, đánh giá trên test) ===")
rows = []
for pct in (0.5, 1, 2, 5):
    thr = max(1, int(np.ceil(np.quantile(train.stars_day_30, 1 - pct / 100))))
    rows.append((f"top {pct}%", thr))
for k in (5, 10, 20, 50):
    rows.append((f">= {k} stars", k))
print(f"{'nhãn':<14}{'ngưỡng':>8}{'%dương train':>14}{'%dương test':>13}{'số dương test':>15}{'AUC baseline':>14}")
for name, thr in rows:
    ytr, yte = train.stars_day_30 >= thr, test.stars_day_30 >= thr
    auc = roc_auc_score(yte, test.stars_day_7) if yte.nunique() > 1 else float("nan")
    print(f"{name:<14}{thr:>8}{ytr.mean() * 100:>14.3f}{yte.mean() * 100:>13.3f}{int(yte.sum()):>15,}{auc:>14.3f}")
print("\nGợi ý: chọn nhãn có >= 200 repo dương ở tập test; nếu AUC baseline > 0.97 thì bài toán rất dễ,\n"
      "báo cáo cần nhấn mạnh phần học máy thêm được bao nhiêu so với baseline.")

print("\n=== 3. Gợi ý số liệu cho 3 kịch bản mẫu (trung vị đặc trưng theo nhóm stars_30) ===")
feats = ["stars_day_1", "stars_day_3", "stars_day_7", "forks_day_7", "total_pushes_7d", "total_commits_7d",
         "unique_contributors_7d", "issues_opened_7d", "issues_closed_7d", "pr_opened_7d",
         "unique_stargazers_7d", "desc_length", "has_trending_keywords"]
r = df.stars_day_30.rank(pct=True, method="first")
for name, lo, hi in (("Dự án cá nhân mới", 0.40, 0.60), ("Khởi đầu khá", 0.93, 0.97), ("Khởi đầu bùng nổ", 0.99, 1.0)):
    print(name, "=", df.loc[(r >= lo) & (r <= hi), feats].median().round().astype(int).to_dict())
