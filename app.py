"""Demo đồ án Nhập môn Big Data: phân tích GH Archive và dự đoán độ phổ biến của repository."""
from __future__ import annotations

import json
from pathlib import Path

# pyrefly: ignore[missing-import]
import joblib
# pyrefly: ignore[missing-import]
import numpy as np
import pandas as pd
# pyrefly: ignore[missing-import]
import plotly.express as px
# pyrefly: ignore[missing-import]
import plotly.graph_objects as go
# pyrefly: ignore[missing-import]
import streamlit as st

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
MODELS_DIR = BASE / "models"
METRICS_DIR = BASE / "metrics"

# Bảng màu lấy từ chính GitHub: xanh liên kết, vàng của ngôi sao, tím của PR đã merge.
BLUE, GOLD, PURPLE, GREEN = "#0969DA", "#BF8700", "#8250DF", "#1A7F37"
INK, MUTED, GRID = "#1F2328", "#6E7781", "#D0D7DE"

# Nhãn lấy từ metrics.json (do make_metrics.py ghi) để app luôn khớp với mô hình đã huấn luyện.
def _get_metrics_json():
    for p in (METRICS_DIR / "metrics.json", BASE / "metrics.json"):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}

_METRICS_DATA = _get_metrics_json()
_LABEL = _METRICS_DATA.get("label", {})
TRENDING_THRESHOLD = int(_LABEL.get("threshold_stars", 50))   # ngưỡng stars ngày 30
LABEL_NAME = _LABEL.get("name", "Trending")
GROUP_TREND, GROUP_OTHER = f"{LABEL_NAME} (≥ {TRENDING_THRESHOLD} stars)", "Còn lại"

# name -> (nhóm, nhãn hiển thị, ý nghĩa)
FEATURE_INFO = {
    "stars_day_1": ("Lan tỏa sớm", "Stars ngày 1", "Stars tích lũy sau 1 ngày"),
    "stars_day_3": ("Lan tỏa sớm", "Stars ngày 3", "Stars tích lũy sau 3 ngày"),
    "stars_day_7": ("Lan tỏa sớm", "Stars ngày 7", "Stars tích lũy sau 7 ngày"),
    "forks_day_7": ("Lan tỏa sớm", "Forks ngày 7", "Forks tích lũy sau 7 ngày"),
    "star_growth_rate": ("Lan tỏa sớm", "Tốc độ tăng star", "(stars ngày 7 − ngày 1) / (ngày 1 + 1)"),
    "total_pushes_7d": ("Phát triển mã", "Số lần push", "Tổng PushEvent trong 7 ngày"),
    "total_commits_7d": ("Phát triển mã", "Số commit", "Tổng commit trong 7 ngày"),
    "unique_contributors_7d": ("Phát triển mã", "Số contributor", "Người đóng góp khác nhau trong 7 ngày"),
    "issues_opened_7d": ("Cộng đồng", "Issues đã mở", "IssuesEvent mở trong 7 ngày"),
    "issues_closed_7d": ("Cộng đồng", "Issues đã đóng", "IssuesEvent đóng trong 7 ngày"),
    "pr_opened_7d": ("Cộng đồng", "PR đã mở", "PullRequestEvent mở trong 7 ngày"),
    "unique_stargazers_7d": ("Cộng đồng", "Số người star", "Tài khoản khác nhau đã star trong 7 ngày"),
    "desc_length": ("Mô tả", "Độ dài mô tả", "Số ký tự của mô tả repo"),
    "has_trending_keywords": ("Mô tả", "Từ khóa xu hướng", "Mô tả chứa ai, llm, agent, rust, web3, rag..."),
}
DEFAULT_FEATURES = list(FEATURE_INFO)

PRESETS = {
    "Dự án cá nhân mới": dict(stars_day_1=0, stars_day_3=0, stars_day_7=0, forks_day_7=0, total_pushes_7d=2,
                              total_commits_7d=2, unique_contributors_7d=1, issues_opened_7d=0,
                              issues_closed_7d=0, pr_opened_7d=0, unique_stargazers_7d=0,
                              desc_length=0, has_trending_keywords=0),
    "Khởi đầu khá": dict(stars_day_1=0, stars_day_3=0, stars_day_7=1, forks_day_7=0, total_pushes_7d=3,
                         total_commits_7d=3, unique_contributors_7d=1, issues_opened_7d=0,
                         issues_closed_7d=0, pr_opened_7d=0, unique_stargazers_7d=1,
                         desc_length=0, has_trending_keywords=0),
    "Khởi đầu bùng nổ": dict(stars_day_1=1, stars_day_3=2, stars_day_7=3, forks_day_7=0, total_pushes_7d=4,
                             total_commits_7d=5, unique_contributors_7d=1, issues_opened_7d=0,
                             issues_closed_7d=0, pr_opened_7d=0, unique_stargazers_7d=3,
                             desc_length=0, has_trending_keywords=0),
}

st.set_page_config(page_title="GitHub repository popularity", page_icon="⭐", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 2.2rem; max-width: 1200px;}
    [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
    h1 {letter-spacing: -0.02em;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- tiện ích
def show(fig: go.Figure, key: str | None = None) -> None:
    """Vẽ biểu đồ plotly với giao diện thống nhất (tương thích nhiều bản Streamlit)."""
    fig.update_layout(
        template="plotly_white",
        font=dict(color=INK, size=13),
        margin=dict(l=10, r=10, t=50, b=10),
        title=dict(font=dict(size=15)),
        legend=dict(title=None, orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except Exception:  # noqa: BLE001  (bản Streamlit cũ chưa hỗ trợ width="stretch")
        st.plotly_chart(fig, use_container_width=True, key=key)


def stretch(fn, *args, **kwargs):
    """Gọi widget với chiều rộng đầy đủ, tương thích cả bản Streamlit cũ lẫn mới."""
    try:
        return fn(*args, width="stretch", **kwargs)
    except Exception:  # noqa: BLE001  (bản Streamlit cũ chưa hỗ trợ width="stretch")
        return fn(*args, use_container_width=True, **kwargs)


def load_json(name: str) -> dict | None:
    for folder in (METRICS_DIR, BASE):
        path = folder / name
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    return None


@st.cache_data
def load_data() -> pd.DataFrame:
    data_path = DATA_DIR / "gold_data_local.csv"
    if not data_path.exists():
        data_path = BASE / "gold_data_local.csv"
    df = pd.read_csv(data_path)
    df["primary_language"] = df.get("primary_language", pd.Series("Unknown", index=df.index)).fillna("Unknown")
    if "stars_day_30" in df.columns:  # tính lại nhãn theo ngưỡng của mô hình
        df["is_trending"] = (df["stars_day_30"] >= TRENDING_THRESHOLD).astype(int)
        df["log_stars_30"] = np.log1p(df["stars_day_30"])
    df["nhom"] = np.where(df["is_trending"] == 1, GROUP_TREND, GROUP_OTHER)
    return df


@st.cache_resource
def load_models(_df: pd.DataFrame):
    """Trả về (model hồi quy, model phân loại, danh sách đặc trưng, đã huấn luyện lại tạm thời?)."""
    reg_path = MODELS_DIR / "reg_model.pkl"
    if not reg_path.exists():
        reg_path = BASE / "reg_model.pkl"
    cls_path = MODELS_DIR / "cls_model.pkl"
    if not cls_path.exists():
        cls_path = BASE / "cls_model.pkl"

    try:
        reg, cls = joblib.load(reg_path), joblib.load(cls_path)
        retrained = False
    except Exception:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

        X = _df[DEFAULT_FEATURES].fillna(0)
        reg = RandomForestRegressor(n_estimators=30, random_state=42).fit(X, _df["log_stars_30"].fillna(0))
        cls = RandomForestClassifier(n_estimators=30, random_state=42).fit(X, _df["is_trending"].fillna(0))
        retrained = True
    features = list(getattr(reg, "feature_names_in_", DEFAULT_FEATURES))
    return reg, cls, features, retrained


def build_row(values: dict, features: list[str], defaults: pd.Series | None = None) -> pd.DataFrame:
    """Ghép giá trị nhập thành 1 dòng đúng thứ tự cột mà mô hình đã học.

    Đặc trưng mà form không có (ví dụ khi mô hình học nhiều đặc trưng hơn form) lấy theo `defaults`
    (trung vị của tập dữ liệu) thay vì 0, để không làm lệch dự đoán.
    """
    v = dict(values)
    v["star_growth_rate"] = (v["stars_day_7"] - v["stars_day_1"]) / (v["stars_day_1"] + 1)
    fallback = (lambda f: float(defaults[f])) if defaults is not None else (lambda f: 0.0)
    return pd.DataFrame([{f: float(v[f]) if f in v else fallback(f) for f in features}])


def tree_interval(model, X: pd.DataFrame, lo: int = 10, hi: int = 90):
    """Khoảng dự đoán từ phân tán giữa các cây (chỉ với Random Forest)."""
    if model.__class__.__name__ not in ("RandomForestRegressor", "ExtraTreesRegressor"):
        return None
    preds = np.array([t.predict(X.to_numpy()) for t in model.estimators_])
    return np.percentile(preds, lo), np.percentile(preds, hi)


def contributions(model, row: pd.DataFrame, medians: pd.Series) -> pd.Series:
    """Mức đẩy lên/kéo xuống của từng đặc trưng so với repo 'trung vị' (thay riêng đặc trưng đó bằng trung vị)."""
    base = model.predict(row)[0]
    alt = pd.concat([row] * len(row.columns), ignore_index=True)
    for i, col in enumerate(row.columns):
        alt.loc[i, col] = medians[col]
    return pd.Series(base - model.predict(alt), index=row.columns).sort_values()


# ---------------------------------------------------------------- tải dữ liệu
try:
    df = load_data()
    reg_model, cls_model, features, retrained = load_models(df)
except Exception as exc:  # noqa: BLE001
    st.error(
        "Không tải được dữ liệu hoặc mô hình. Đặt `gold_data_local.csv`, `reg_model.pkl` và "
        f"`cls_model.pkl` cùng thư mục với `app.py`.\n\nChi tiết: {exc}"
    )
    st.stop()

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Bộ lọc")
    languages = ["Tất cả"] + sorted(df["primary_language"].unique().tolist())
    selected_lang = st.selectbox("Ngôn ngữ chính", languages)
    hide_unknown = st.checkbox("Ẩn repo không rõ ngôn ngữ", value=False)
    st.caption("Bộ lọc chỉ áp dụng cho tab Tổng quan dữ liệu.")
    st.divider()
    st.caption(f"Bảng Gold: {len(df):,} repository, {len(features)} đặc trưng đưa vào mô hình.")
    if retrained:
        st.warning(
            "Không tìm thấy file mô hình. Ứng dụng đang dùng mô hình tạm huấn luyện trên toàn bộ dữ liệu; "
            "không dùng để báo cáo số liệu."
        )

fdf = df
if selected_lang != "Tất cả":
    fdf = fdf[fdf["primary_language"] == selected_lang]
if hide_unknown:
    fdf = fdf[fdf["primary_language"] != "Unknown"]

# ---------------------------------------------------------------- tiêu đề
st.title("Dự đoán độ phổ biến của GitHub repository")
st.caption(
    "Từ hoạt động trong 7 ngày đầu, ước lượng số stars ở ngày thứ 30 và khả năng trở thành repo nổi bật. "
    "Dữ liệu: GH Archive, xử lý bằng Apache Spark."
)

tab_eda, tab_pred, tab_model, tab_perf, tab_arch = st.tabs(
    ["Tổng quan dữ liệu", "Dự đoán", "Chất lượng mô hình", "Hiệu năng Big Data", "Kiến trúc và dữ liệu"]
)

# ================================================================ TAB 1: EDA
with tab_eda:
    scope = selected_lang if selected_lang != "Tất cả" else "toàn bộ ngôn ngữ"
    st.subheader("Tổng quan dữ liệu")
    st.caption(f"Đang xem: {scope}")

    if fdf.empty:
        st.info("Không có repository nào khớp bộ lọc. Hãy chọn ngôn ngữ khác.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Repository", f"{len(fdf):,}")
        k2.metric(f"{LABEL_NAME} (≥ {TRENDING_THRESHOLD} stars)", f"{int(fdf['is_trending'].sum()):,}")
        k3.metric(f"Tỷ lệ {LABEL_NAME.lower()}", f"{fdf['is_trending'].mean() * 100:.2f}%")
        k4.metric("Stars ngày 30 cao nhất", f"{int(np.expm1(fdf['log_stars_30'].max())):,}")

        c1, c2 = st.columns(2)
        with c1:
            fig = px.histogram(
                fdf, x="log_stars_30", color="nhom", nbins=40, barmode="overlay", opacity=0.75,
                color_discrete_map={GROUP_TREND: GOLD, GROUP_OTHER: BLUE},
                labels={"log_stars_30": "log(stars ngày 30 + 1)", "count": "Số repo"},
                title="Phân phối stars lệch phải (power-law), nên dự đoán trên thang log",
            )
            fig.update_yaxes(title="Số repo")
            show(fig, "eda_hist")
        with c2:
            unknown_share = (df["primary_language"] == "Unknown").mean() * 100
            lang = (
                fdf.groupby("primary_language")
                .agg(so_repo=("is_trending", "size"), ty_le=("is_trending", "mean"))
                .query("so_repo >= 30")
                .sort_values("ty_le", ascending=False)
                .head(12)
                .reset_index()
            )
            if len(lang) >= 2:
                lang["ty_le"] *= 100
                fig = px.bar(
                    lang.sort_values("ty_le"), x="ty_le", y="primary_language", orientation="h",
                    hover_data={"so_repo": True}, color_discrete_sequence=[BLUE],
                    labels={"ty_le": f"Tỷ lệ {LABEL_NAME.lower()} (%)", "primary_language": "", "so_repo": "Số repo"},
                    title=f"Ngôn ngữ có tỷ lệ {LABEL_NAME.lower()} cao nhất (nhóm ≥ 30 repo)",
                )
                show(fig, "eda_lang")
            else:
                st.info("Chưa đủ nhóm ngôn ngữ có ≥ 30 repo để so sánh trong bộ lọc này.")
            st.caption(f"{unknown_share:.0f}% repo không rõ ngôn ngữ (GH Archive chỉ cung cấp ngôn ngữ qua một số loại sự kiện).")

        c3, c4 = st.columns(2)
        with c3:
            curve = (
                fdf.groupby("nhom")[["stars_day_1", "stars_day_3", "stars_day_7"]].mean()
                .rename(columns={"stars_day_1": "1", "stars_day_3": "3", "stars_day_7": "7"})
                .T.reset_index().rename(columns={"index": "ngay"})
                .melt(id_vars="ngay", var_name="nhom", value_name="stars_tb")
            )
            fig = px.line(
                curve, x="ngay", y="stars_tb", color="nhom", markers=True,
                color_discrete_map={GROUP_TREND: GOLD, GROUP_OTHER: BLUE},
                labels={"ngay": "Ngày kể từ khi tạo repo", "stars_tb": "Stars trung bình"},
                title=f"Repo {LABEL_NAME.lower()} tăng tốc ngay từ những ngày đầu",
            )
            show(fig, "eda_curve")
        with c4:
            sample = fdf.sample(min(2000, len(fdf)), random_state=1).copy()
            sample["log_stars_7"] = np.log1p(sample["stars_day_7"])
            fig = px.scatter(
                sample, x="log_stars_7", y="log_stars_30", color="nhom", opacity=0.55,
                color_discrete_map={GROUP_TREND: GOLD, GROUP_OTHER: BLUE},
                labels={"log_stars_7": "log(stars ngày 7 + 1)", "log_stars_30": "log(stars ngày 30 + 1)"},
                title="Stars ngày 7 so với ngày 30 (mẫu 2.000 repo)",
            )
            show(fig, "eda_scatter")

        num_cols = [c for c in features if c in fdf.columns] + ["log_stars_30"]
        corr = fdf[num_cols].sample(min(20000, len(fdf)), random_state=1).corr(method="spearman")
        fig = px.imshow(
            corr, zmin=-1, zmax=1, text_auto=".2f", aspect="auto",
            color_continuous_scale=[[0, PURPLE], [0.5, "#FFFFFF"], [1, BLUE]],
            title="Tương quan Spearman giữa đặc trưng và log(stars ngày 30)",
        )
        fig.update_layout(height=560)
        show(fig, "eda_corr")

        if {"created_hour", "created_dow"}.issubset(fdf.columns):
            heat = fdf.pivot_table(index="created_dow", columns="created_hour", values="is_trending", aggfunc="size", fill_value=0)
            show(px.imshow(heat, aspect="auto", color_continuous_scale=[[0, "#FFFFFF"], [1, BLUE]],
                           labels=dict(x="Giờ (UTC)", y="Thứ", color="Số repo"),
                           title="Thời điểm repo được tạo"), "eda_heat")

# ================================================================ TAB 2: DỰ ĐOÁN
with tab_pred:
    st.subheader("Dự đoán độ phổ biến sau 30 ngày")
    st.caption("Nhập số liệu 7 ngày đầu của một repository, hoặc chọn một kịch bản mẫu rồi chỉnh tiếp.")

    for k, v in PRESETS["Khởi đầu khá"].items():
        st.session_state.setdefault(f"in_{k}", v)

    def apply_preset(name: str) -> None:
        for key, val in PRESETS[name].items():
            st.session_state[f"in_{key}"] = val

    pcols = st.columns(len(PRESETS))
    for col, name in zip(pcols, PRESETS):
        stretch(col.button, name, on_click=apply_preset, args=(name,))

    with st.form("prediction_form"):
        st.markdown("**Lan tỏa sớm** (số liệu tích lũy)")
        a = st.columns(4)
        a[0].number_input("Stars ngày 1", min_value=0, key="in_stars_day_1")
        a[1].number_input("Stars ngày 3", min_value=0, key="in_stars_day_3")
        a[2].number_input("Stars ngày 7", min_value=0, key="in_stars_day_7")
        a[3].number_input("Forks ngày 7", min_value=0, key="in_forks_day_7")

        st.markdown("**Phát triển mã nguồn**")
        b = st.columns(3)
        b[0].number_input("Số lần push", min_value=0, key="in_total_pushes_7d")
        b[1].number_input("Số commit", min_value=0, key="in_total_commits_7d")
        b[2].number_input("Số contributor", min_value=0, key="in_unique_contributors_7d")

        st.markdown("**Cộng đồng**")
        c = st.columns(4)
        c[0].number_input("Issues đã mở", min_value=0, key="in_issues_opened_7d")
        c[1].number_input("Issues đã đóng", min_value=0, key="in_issues_closed_7d")
        c[2].number_input("PR đã mở", min_value=0, key="in_pr_opened_7d")
        c[3].number_input("Số người star", min_value=0, key="in_unique_stargazers_7d")

        st.markdown("**Mô tả repo**")
        d = st.columns([3, 2])
        d[0].slider("Độ dài mô tả (ký tự)", 0, 300, key="in_desc_length")
        d[1].selectbox(
            "Mô tả có từ khóa xu hướng (AI, LLM, Rust, Agent...)",
            [1, 0], format_func=lambda x: "Có" if x == 1 else "Không", key="in_has_trending_keywords",
        )
        submitted = st.form_submit_button("Dự đoán", type="primary")

    if submitted:
        vals = {k: st.session_state[f"in_{k}"] for k in PRESETS["Khởi đầu khá"]}
        problems = []
        if not (vals["stars_day_1"] <= vals["stars_day_3"] <= vals["stars_day_7"]):
            problems.append("Stars là số tích lũy nên phải thỏa: ngày 1 ≤ ngày 3 ≤ ngày 7.")
        if vals["unique_stargazers_7d"] > vals["stars_day_7"]:
            problems.append("Số người star không thể lớn hơn stars ngày 7.")

        if problems:
            for msg in problems:
                st.error(msg)
        else:
            if vals["issues_closed_7d"] > vals["issues_opened_7d"]:
                st.warning("Issues đã đóng nhiều hơn issues đã mở, kết quả có thể kém tin cậy.")

            med = df.reindex(columns=features).median(numeric_only=True).fillna(0)
            row = build_row(vals, features, med)
            pred_log = float(reg_model.predict(row)[0])
            floor = float(np.log1p(vals["stars_day_7"]))
            clamped = pred_log < floor
            pred_log = max(pred_log, floor)  # stars tích lũy không thể giảm
            prob = float(cls_model.predict_proba(row)[0][1]) * 100
            interval = tree_interval(reg_model, row)
            percentile = float((df["log_stars_30"] < pred_log).mean() * 100)

            r1, r2 = st.columns(2)
            with r1:
                with st.container(border=True):
                    st.metric("Stars dự kiến ở ngày 30", f"{int(np.expm1(pred_log)):,}")
                    if interval:
                        lo, hi = max(np.expm1(interval[0]), vals["stars_day_7"]), np.expm1(interval[1])
                        st.caption(f"Khoảng dự đoán 10–90%: {int(lo):,} đến {int(max(hi, lo)):,} stars")
                    st.caption(f"Cao hơn khoảng {percentile:.0f}% repo trong tập dữ liệu.")
                    if clamped:
                        st.caption("Đã điều chỉnh để không thấp hơn số stars hiện có ở ngày 7.")
            with r2:
                with st.container(border=True):
                    st.metric(f"Xác suất đạt ≥ {TRENDING_THRESHOLD} stars", f"{prob:.1f}%")
                    gauge = go.Figure(go.Indicator(
                        mode="gauge", value=prob,
                        gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=GOLD),
                                   steps=[dict(range=[0, 30], color="#EAEEF2"), dict(range=[30, 60], color="#D0D7DE"),
                                          dict(range=[60, 100], color="#AFB8C1")]),
                    ))
                    gauge.update_layout(height=150, margin=dict(l=10, r=10, t=10, b=0))
                    show(gauge, "pred_gauge")
                    verdict = (f"Khả năng cao trở thành repo {LABEL_NAME.lower()}." if prob >= 60
                               else "Khả năng trung bình, cần theo dõi thêm." if prob >= 30
                               else "Khả năng thấp, nhiều khả năng tăng trưởng bình thường.")
                    st.caption(verdict)

            contrib = contributions(reg_model, row, med)
            cdf = pd.DataFrame({
                "feature": [FEATURE_INFO.get(f, ("", f, ""))[1] for f in contrib.index],
                "delta": contrib.values,
            })
            cdf["huong"] = np.where(cdf["delta"] >= 0, "Đẩy dự đoán lên", "Kéo dự đoán xuống")
            fig = px.bar(
                cdf, x="delta", y="feature", orientation="h", color="huong",
                color_discrete_map={"Đẩy dự đoán lên": GREEN, "Kéo dự đoán xuống": PURPLE},
                labels={"delta": "Thay đổi log(stars + 1) so với repo trung vị", "feature": ""},
                title="Yếu tố nào làm dự đoán cao hoặc thấp hơn repo trung vị?",
            )
            show(fig, "pred_contrib")
            st.caption("Ước lượng bằng cách thay riêng từng đặc trưng bằng giá trị trung vị của tập dữ liệu rồi so sánh dự đoán.")

# ================================================================ TAB 3: MÔ HÌNH
with tab_model:
    st.subheader("Chất lượng mô hình")
    metrics = load_json("metrics.json")
    if metrics is None:
        st.info("Chưa có `metrics.json`. Chạy `python make_metrics.py` để đánh giá trên tập kiểm tra chia theo thời gian và so với baseline.")
    else:
        n_tr, n_te = metrics.get("n_train"), metrics.get("n_test")
        sizes = f" ({n_tr:,} train, {n_te:,} test)" if isinstance(n_tr, int) and isinstance(n_te, int) else ""
        st.caption(f"Cách chia dữ liệu: {metrics.get('split', 'không rõ')}{sizes}.")
        lab = metrics.get("label")
        if lab:
            st.caption(
                f"Nhãn: {lab.get('definition', '')}. Tỷ lệ dương tính ở tập test: "
                f"{metrics.get('positive_rate_test', 0) * 100:.2f}% ({metrics.get('n_pos_test', 0):,} repo)."
            )
        for title, key in (("Hồi quy: log(stars ngày 30 + 1)", "regression"), (f"Phân loại: repo {LABEL_NAME.lower()}", "classification")):
            if key in metrics:
                st.markdown(f"**{title}**")
                table = pd.DataFrame.from_dict(metrics[key], orient="index")
                stretch(st.dataframe, table.style.format("{:.3f}"))
        st.caption("Baseline chỉ dùng số stars ngày 7. Mô hình có giá trị khi vượt rõ baseline.")
        if "ablation" in metrics:
            st.markdown("**Loại trừ từng nhóm đặc trưng (ablation, trung bình 3 lần chạy)**")
            stretch(st.dataframe, pd.DataFrame.from_dict(metrics["ablation"], orient="index").style.format("{:.3f}"))
            st.caption("Chênh lệch nhỏ hơn độ lệch chuẩn (cột std) chưa đủ để kết luận một nhóm đặc trưng quan trọng.")

    imp_cols = st.columns(2)
    for col, (name, mdl) in zip(imp_cols, (("hồi quy", reg_model), ("phân loại", cls_model))):
        if hasattr(mdl, "feature_importances_"):
            imp = pd.DataFrame({
                "feature": [FEATURE_INFO.get(f, ("", f, ""))[1] for f in features],
                "importance": mdl.feature_importances_,
            }).sort_values("importance")
            fig = px.bar(imp, x="importance", y="feature", orientation="h", color_discrete_sequence=[BLUE],
                         labels={"importance": "Độ quan trọng", "feature": ""},
                         title=f"Độ quan trọng của đặc trưng ({name})")
            with col:
                show(fig, f"imp_{name}")

# ================================================================ TAB 4: HIỆU NĂNG
with tab_perf:
    st.subheader("Hiệu năng xử lý dữ liệu lớn")
    bench_path = METRICS_DIR / "benchmark.csv"
    if not bench_path.exists():
        bench_path = BASE / "benchmark.csv"
    if not bench_path.exists():
        st.info("Chưa có `benchmark.csv`. Thêm file với các cột `experiment, config, value, unit` để hiển thị kết quả benchmark.")
        st.code(
            "experiment,config,value,unit\n"
            "Định dạng lưu trữ,JSON.gz,412.0,giây\n"
            "Định dạng lưu trữ,Parquet (Snappy),38.5,giây\n"
            "Số luồng xử lý,local[1],980.0,giây\n"
            "Số luồng xử lý,local[2],540.0,giây\n"
            "Số luồng xử lý,local[4],310.0,giây",
            language="csv",
        )
        st.caption("Số trong ví dụ chỉ để minh họa định dạng file.")
    else:
        bench = pd.read_csv(bench_path)
        exps = bench["experiment"].unique().tolist()
        for i in range(0, len(exps), 2):
            cols = st.columns(2)
            for col, exp in zip(cols, exps[i:i + 2]):
                part = bench[bench["experiment"] == exp].reset_index(drop=True)
                unit = part["unit"].iloc[0] if "unit" in part else ""
                fig = px.bar(part, x="config", y="value", text="value", color_discrete_sequence=[BLUE],
                             labels={"config": "", "value": unit}, title=exp)
                fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
                with col:
                    show(fig, f"bench_{exp}")
                    if len(part) > 1 and part["value"].iloc[1:].min() > 0:
                        best = part.loc[part["value"].idxmin()]
                        st.caption(f"Nhanh nhất: {best['config']}, nhanh gấp {part['value'].iloc[0] / best['value']:.1f} lần so với {part['config'].iloc[0]}.")

    images = sorted([*(BASE / "assets").glob("*.png"), *(BASE / "assets").glob("*.jpg")]) if (BASE / "assets").exists() else []
    if images:
        st.markdown("**Minh chứng thực thi trên Spark UI**")
        for img in images:
            with st.expander(img.stem.replace("_", " ")):
                st.image(str(img))
    else:
        st.caption("Đặt ảnh chụp Spark UI (DAG, Stages, Shuffle) vào thư mục `assets/` để hiển thị tại đây.")

# ================================================================ TAB 5: KIẾN TRÚC
with tab_arch:
    st.subheader("Kiến trúc và dữ liệu")
    st.graphviz_chart(
        """
        digraph G {
          rankdir=LR; bgcolor="transparent";
          node [shape=box, style="rounded,filled", fillcolor="#F6F8FA", color="#D0D7DE", fontname="Helvetica", fontsize=11];
          edge [color="#6E7781"];
          src [label="GH Archive\\n.json.gz theo giờ"];
          bronze [label="Bronze\\nbản gốc"];
          silver [label="Silver\\nlọc bot, làm phẳng\\nParquet theo ngày"];
          gold [label="Gold\\nbảng đặc trưng\\nmỗi dòng một repo"];
          ml [label="Huấn luyện\\nvà đánh giá"];
          app [label="Streamlit\\n(demo này)"];
          src -> bronze -> silver -> gold -> ml -> app;
        }
        """
    )

    stats = load_json("pipeline_stats.json")
    if stats:
        st.markdown("**Số liệu pipeline**")
        cols = st.columns(min(4, len(stats)))
        for i, (label, value) in enumerate(stats.items()):
            cols[i % len(cols)].metric(label, f"{value:,}" if isinstance(value, (int, float)) else str(value))
    else:
        st.caption("Thêm `pipeline_stats.json` (ví dụ số bản ghi trước/sau lọc bot, dung lượng JSON và Parquet) để hiển thị số liệu thật của pipeline.")

    st.markdown("**Từ điển đặc trưng**")
    dictionary = pd.DataFrame(
        [(name, grp, label, desc) for name, (grp, label, desc) in FEATURE_INFO.items()],
        columns=["Đặc trưng", "Nhóm", "Tên hiển thị", "Ý nghĩa"],
    )
    stretch(st.dataframe, dictionary, hide_index=True)

    with st.expander("Phạm vi và hạn chế"):
        st.markdown(
            "- Mô hình chỉ học từ các đặc trưng trong bảng trên, tính trong 7 ngày đầu của repo.\n"
            "- Kết quả là ước lượng thống kê theo dữ liệu huấn luyện, không phải cam kết về tương lai của một repo.\n"
            "- Ngôn ngữ lập trình chỉ có với một phần repo nên nhóm \"Unknown\" lớn.\n"
            "- Tác vụ ETL chạy trên Spark ở chế độ local; chưa phải cụm nhiều máy."
        )
