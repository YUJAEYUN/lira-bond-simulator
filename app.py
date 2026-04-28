import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(
    page_title="미국채 + 리라채 수익 시뮬레이터",
    page_icon="📈",
    layout="wide"
)

DATA_DIR = "dataset/"


@st.cache_data
def load_data():
    def load_csv(filename, col):
        df = pd.read_csv(DATA_DIR + filename, encoding="utf-8-sig")
        df["날짜"] = pd.to_datetime(
            df["날짜"].str.replace(" ", "", regex=False), format="%Y-%m-%d"
        )
        df[col] = (
            df["종가"].astype(str).str.replace(",", "", regex=False).str.strip().astype(float)
        )
        return df[["날짜", col]].sort_values("날짜").reset_index(drop=True)

    def load_try_xlsx(filename, col):
        df = pd.read_excel(DATA_DIR + filename)
        df = df.dropna(subset=["날짜", "금리"])
        df["날짜"] = pd.to_datetime(df["날짜"], format="%m/%d/%Y")
        df[col] = df["금리"].astype(float)
        return df[["날짜", col]].sort_values("날짜").reset_index(drop=True)

    usdkrw  = load_csv("usd_krw.csv",      "usdkrw")
    usdtry  = load_csv("usd_try.csv",      "usdtry")
    us_yld  = load_csv("us_yield_1y.csv",  "us_yield")
    try_yld = load_try_xlsx("try_yield_1y.xlsx", "try_yield")

    df = (
        usdkrw.merge(usdtry,  on="날짜", how="inner")
               .merge(us_yld,  on="날짜", how="inner")
               .merge(try_yld, on="날짜", how="inner")
    )
    df["trykrw"]     = df["usdkrw"] / df["usdtry"]
    df["usd_mom60"]  = df["usdkrw"].pct_change(60)
    df["usd_strong"] = df["usd_mom60"] > 0
    return df


df = load_data()
DATE_MIN = df["날짜"].min().date()
DATE_MAX = df["날짜"].max().date()


# ── 사이드바 ───────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 시뮬레이션 설정")
    st.divider()

    scale_eok = st.number_input(
        "💰 투자원금 (억원)", min_value=10, max_value=50000, value=100, step=10
    )

    loan_rate_pct = st.slider(
        "🏦 대출금리 (%/년)", min_value=1.0, max_value=20.0, value=6.0, step=0.5
    )

    lev_pct = st.slider(
        "📊 레버리지 비율 (미국채 대비 차입 %)", min_value=10, max_value=100, value=50, step=5
    )

    st.divider()

    entry_opt = st.selectbox(
        "📅 진입일",
        ["2023-01-02", "2024-01-02", "2025-01-02", "2026-01-02", "직접 입력"],
    )
    if entry_opt == "직접 입력":
        custom_entry = st.date_input("진입일 선택", value=pd.Timestamp("2024-01-02"), min_value=DATE_MIN, max_value=DATE_MAX)
        entry_str = str(custom_entry)
    else:
        entry_str = entry_opt

    period_type = st.radio(
        "📆 기간",
        ["진입일 ~ 현재", "해당 연도 1년만"],
        index=0,
    )

    st.divider()
    show_regime = st.toggle("USD 강세/약세 구간 표시", value=True)
    regime_window = st.slider("강세/약세 판단 기준 (거래일)", 20, 120, 60, 10,
                               help="최근 N거래일 대비 USD/KRW 상승 여부로 판단")


# ── 계산 ──────────────────────────────────────────────────────────────
LOAN_RATE = loan_rate_pct / 100
LEV_RATIO = lev_pct / 100
SCALE_KRW = scale_eok * 1_0000_0000

entry_row = df[df["날짜"] >= pd.Timestamp(entry_str)].iloc[0]
ed = entry_row["날짜"]

if period_type == "해당 연도 1년만":
    exit_date = pd.Timestamp(f"{ed.year}-12-31")
    data = df[(df["날짜"] >= ed) & (df["날짜"] <= exit_date)].copy()
else:
    data = df[df["날짜"] >= ed].copy()

usdkrw_0 = entry_row["usdkrw"]
usdtry_0 = entry_row["usdtry"]
trykrw_0  = entry_row["trykrw"]
us_c      = entry_row["us_yield"]  / 100
try_c     = entry_row["try_yield"] / 100

approx_spread = try_c - LOAN_RATE
exact_bep_change = (1 + LOAN_RATE) / (1 + try_c) - 1

data = data.copy()
data["t"] = (data["날짜"] - ed).dt.days / 365

# 전략 A: 미국채 단독
data["us_coupon_usd"] = us_c * data["t"]
data["us_val_krw"]    = (1.0 + data["us_coupon_usd"]) * data["usdkrw"]
data["us_ret"]        = (data["us_val_krw"] - usdkrw_0) / usdkrw_0 * 100

# 전략 B: 미국채 + 리라채
try_princ              = LEV_RATIO * usdtry_0
data["try_coupon_try"] = try_c * data["t"] * try_princ
data["try_val_krw"]    = (try_princ + data["try_coupon_try"]) * data["trykrw"]
data["repay_krw"]      = LEV_RATIO * (1 + LOAN_RATE * data["t"]) * data["usdkrw"]
data["lev_net_krw"]    = data["try_val_krw"] - data["repay_krw"]
data["lev_val_krw"]    = data["us_val_krw"] + data["lev_net_krw"]
data["lev_ret"]        = (data["lev_val_krw"] - usdkrw_0) / usdkrw_0 * 100
data["alpha"]          = data["lev_ret"] - data["us_ret"]

eok = scale_eok / 100
data["us_eok"]  = data["us_ret"]  * eok
data["lev_eok"] = data["lev_ret"] * eok
data["alp_eok"] = data["alpha"]   * eok

# 수익 분해
data["us_coupon_d"]  = us_c * data["t"] * 100 * eok
data["us_fx_d"]      = (1 + us_c * data["t"]) * (data["usdkrw"] - usdkrw_0) / usdkrw_0 * 100 * eok
data["try_coupon_d"] = try_c * data["t"] * LEV_RATIO * 100 * eok
data["try_fx_d"]     = LEV_RATIO * usdtry_0 * (1 + try_c * data["t"]) * (data["trykrw"] - trykrw_0) / usdkrw_0 * 100 * eok
data["borrow_d"]     = -(data["repay_krw"] - LEV_RATIO * usdkrw_0) / usdkrw_0 * 100 * eok

data["usd_regime"] = data["usdkrw"].pct_change(regime_window) > 0

usd_principal = SCALE_KRW / usdkrw_0
last = data.iloc[-1]


# ── 헤더 ──────────────────────────────────────────────────────────────
st.title("📈 미국채 + 리라채 수익 시뮬레이터")
st.caption(
    f"진입일 {ed.strftime('%Y.%m.%d')}  |  미국채 쿠폰 **{us_c*100:.2f}%**  |  "
    f"리라채 쿠폰 **{try_c*100:.2f}%**  |  대출금리 **{loan_rate_pct:.1f}%**  |  "
    f"레버리지 **{lev_pct}%**"
)

# ── 핵심 지표 ─────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "전략 A  (미국채 단독)",
    f"{last['us_eok']:+.1f}억",
    f"{last['us_ret']:+.1f}%",
)
c2.metric(
    "전략 B  (미국채 + 리라채)",
    f"{last['lev_eok']:+.1f}억",
    f"{last['lev_ret']:+.1f}%",
    delta_color="normal" if last["alp_eok"] >= 0 else "inverse",
)
c3.metric(
    "리라채 추가 효과",
    f"{last['alp_eok']:+.1f}억",
    "추가 수익" if last["alp_eok"] >= 0 else "추가 손실",
    delta_color="normal" if last["alp_eok"] >= 0 else "inverse",
)
c4.metric(
    "USD/KRW (진입 → 현재)",
    f"{last['usdkrw']:,.0f}",
    f"{(last['usdkrw'] - usdkrw_0):+.0f} ({(last['usdkrw']/usdkrw_0 - 1)*100:+.1f}%)",
    delta_color="off",
)

st.divider()

# ── BEP 및 이자 쿠션 효과 분석 ─────────────────────────────────────────
st.subheader("🛡️ 핵심 리스크 방어 논리 (이자 쿠션 및 손익분기점)")

actual_t = last["t"]
st.caption(f"CFO 미팅용 세일즈 포인트: '선택하신 기간({actual_t*365:.0f}일, 약 {actual_t:.1f}년) 동안 리라화가 얼마나 폭락해야 원금 손실이 발생하는가?'")

period_bep_change = (1 + LOAN_RATE * actual_t) / (1 + try_c * actual_t) - 1 if actual_t > 0 else 0
actual_try_usd_depreciation = (usdtry_0 / last["usdtry"]) - 1
period_approx_spread = (try_c - LOAN_RATE) * actual_t

bc1, bc2, bc3 = st.columns(3)
bc1.metric(
    f"해당 기간({actual_t:.1f}년) 누적 이자 스프레드",
    f"{period_approx_spread*100:.1f}%",
    help="리라채 쿠폰 - 조달 금리 (선택한 기간 누적 기준)"
)
bc2.metric(
    "해당 기간 누적 손익분기 하락률 (BEP)",
    f"{period_bep_change*100:.1f}%",
    help="이 수치 이상으로 리라화 가치가 폭락하면 원금 손실 발생 (해당 기간 누적 이자 반영)"
)

buffer_margin = abs(period_bep_change) - abs(actual_try_usd_depreciation)
bc3.metric(
    "선택 기간 실제 리라화 하락률",
    f"{actual_try_usd_depreciation*100:.1f}%",
    delta=f"방어 마진: {buffer_margin*100:+.1f}%p",
    delta_color="normal" if buffer_margin >= 0 else "inverse"
)

if buffer_margin >= 0:
    st.success(f"✅ **쿠션 방어 성공**: 실제 누적 환율 하락률({abs(actual_try_usd_depreciation)*100:.1f}%)이 해당 기간 BEP({abs(period_bep_change)*100:.1f}%) 이내여서, 막대한 이자 수익이 환손실을 덮고 추가 수익을 창출했습니다.")
else:
    st.error(f"🚨 **청산/손실 리스크 발생**: 실제 누적 환율 하락률({abs(actual_try_usd_depreciation)*100:.1f}%)이 해당 기간 BEP({abs(period_bep_change)*100:.1f}%)를 초과하여, 이자 쿠션이 뚫리고 손실이 발생했습니다.")

st.divider()


# ── 메인 차트 ──────────────────────────────────────────────────────────
fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=True,
    row_heights=[0.58, 0.21, 0.21],
    vertical_spacing=0.04,
    subplot_titles=[
        "전략별 누적 손익 (억원)",
        "전략 A 수익 분해 — 달러 쿠폰 + 달러 환율",
        "리라채 추가 손익 분해 — 리라 쿠폰 / 리라 환율 / 차입 비용",
    ],
)

# USD 강세/약세 배경 shading
if show_regime:
    regime_col = data["usd_regime"].values
    dates_arr  = data["날짜"].values
    i = 0
    while i < len(regime_col):
        j = i + 1
        while j < len(regime_col) and regime_col[j] == regime_col[i]:
            j += 1
        color = (
            "rgba(255,237,160,0.45)" if regime_col[i]
            else "rgba(191,219,254,0.45)"
        )
        fig.add_vrect(
            x0=str(dates_arr[i])[:10],
            x1=str(dates_arr[min(j, len(dates_arr)-1)])[:10],
            fillcolor=color, opacity=1, layer="below", line_width=0,
        )
        i = j

fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["us_eok"],
        name="전략 A: 미국채 단독",
        line=dict(color="#2563EB", width=2.8),
        hovertemplate="%{x|%Y.%m.%d}  미국채 단독: <b>%{y:+.2f}억</b><extra></extra>",
    ), row=1, col=1,
)
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["lev_eok"],
        name="전략 B: 미국채 + 리라채",
        line=dict(color="#DC2626", width=2.8),
        hovertemplate="%{x|%Y.%m.%d}  리라채 추가: <b>%{y:+.2f}억</b><extra></extra>",
    ), row=1, col=1,
)

pos_mask = data["alp_eok"] >= 0
fig.add_trace(
    go.Scatter(
        x=pd.concat([data.loc[pos_mask, "날짜"], data.loc[pos_mask, "날짜"].iloc[::-1]]),
        y=pd.concat([data.loc[pos_mask, "lev_eok"], data.loc[pos_mask, "us_eok"].iloc[::-1]]),
        fill="toself", fillcolor="rgba(22,163,74,0.18)",
        line=dict(width=0), showlegend=False, hoverinfo="skip", name="추가수익",
    ), row=1, col=1,
)
neg_mask = data["alp_eok"] < 0
fig.add_trace(
    go.Scatter(
        x=pd.concat([data.loc[neg_mask, "날짜"], data.loc[neg_mask, "날짜"].iloc[::-1]]),
        y=pd.concat([data.loc[neg_mask, "lev_eok"], data.loc[neg_mask, "us_eok"].iloc[::-1]]),
        fill="toself", fillcolor="rgba(220,38,38,0.18)",
        line=dict(width=0), showlegend=False, hoverinfo="skip", name="추가손실",
    ), row=1, col=1,
)

fig.add_hline(y=0, line_dash="dot", line_color="#9CA3AF", line_width=1, row=1, col=1)

# Row 2: 전략 A 수익 분해
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["us_coupon_d"],
        name="달러 쿠폰 기여",
        fill="tozeroy", fillcolor="rgba(37,99,235,0.25)",
        line=dict(color="rgba(37,99,235,0.6)", width=1),
        hovertemplate="%{x|%Y.%m.%d}  달러쿠폰: <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row2",
    ), row=2, col=1,
)
us_fx_pos = data["us_fx_d"].clip(lower=0)
us_fx_neg = data["us_fx_d"].clip(upper=0)
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=us_fx_pos,
        name="달러 환율 기여(+)",
        fill="tozeroy", fillcolor="rgba(22,163,74,0.28)",
        line=dict(color="rgba(22,163,74,0.5)", width=0.8),
        hovertemplate="%{x|%Y.%m.%d}  환율(+): <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row2",
    ), row=2, col=1,
)
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=us_fx_neg,
        name="달러 환율 기여(-)",
        fill="tozeroy", fillcolor="rgba(220,38,38,0.28)",
        line=dict(color="rgba(220,38,38,0.5)", width=0.8),
        hovertemplate="%{x|%Y.%m.%d}  환율(-): <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row2",
    ), row=2, col=1,
)
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["us_eok"],
        name="전략 A 합계",
        line=dict(color="#1E3A8A", width=2.2, dash="solid"),
        hovertemplate="%{x|%Y.%m.%d}  A 합계: <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row2",
    ), row=2, col=1,
)
fig.add_hline(y=0, line_dash="dot", line_color="#9CA3AF", line_width=1, row=2, col=1)

# Row 3: 알파 수익 분해
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["try_coupon_d"],
        name="리라채 쿠폰 (환율 제외)",
        fill="tozeroy", fillcolor="rgba(5,150,105,0.28)",
        line=dict(color="rgba(5,150,105,0.6)", width=1),
        hovertemplate="%{x|%Y.%m.%d}  리라쿠폰(순수): <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row3",
    ), row=3, col=1,
)
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["try_fx_d"],
        name="리라 환율 (원금+쿠폰 전체)",
        fill="tozeroy", fillcolor="rgba(217,119,6,0.28)",
        line=dict(color="rgba(217,119,6,0.6)", width=1),
        hovertemplate="%{x|%Y.%m.%d}  리라환율: <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row3",
    ), row=3, col=1,
)
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["borrow_d"],
        name="차입 비용",
        fill="tozeroy", fillcolor="rgba(190,18,60,0.22)",
        line=dict(color="rgba(190,18,60,0.55)", width=1),
        hovertemplate="%{x|%Y.%m.%d}  차입비용: <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row3",
    ), row=3, col=1,
)
fig.add_trace(
    go.Scatter(
        x=data["날짜"], y=data["alp_eok"],
        name="리라채 추가 손익 합계",
        line=dict(color="#7C3AED", width=2.2, dash="solid"),
        hovertemplate="%{x|%Y.%m.%d}  알파 합계: <b>%{y:+.2f}억</b><extra></extra>",
        legendgroup="row3",
    ), row=3, col=1,
)
fig.add_hline(y=0, line_dash="dot", line_color="#9CA3AF", line_width=1, row=3, col=1)

fig.update_layout(
    height=780,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                font=dict(size=13, color="#111827")),
    margin=dict(t=40, b=10, l=10, r=10),
    plot_bgcolor="#F9FAFB",
    paper_bgcolor="#FFFFFF",
)
fig.update_annotations(font=dict(size=13, color="#111827", family="sans-serif"))

fig.update_yaxes(ticksuffix="억", tickformat="+.1f", row=1, col=1,
                 gridcolor="#E5E7EB", tickfont=dict(color="#374151", size=11))
fig.update_yaxes(ticksuffix="억", tickformat="+.1f", row=2, col=1,
                 gridcolor="#E5E7EB", tickfont=dict(color="#374151", size=11))
fig.update_yaxes(ticksuffix="억", tickformat="+.1f", row=3, col=1,
                 gridcolor="#E5E7EB", tickfont=dict(color="#374151", size=11))
fig.update_xaxes(showgrid=False, tickfont=dict(color="#374151", size=11))

if show_regime and len(data) > 0:
    strong_start = data[data["usd_regime"]]["날짜"].iloc[0] if data["usd_regime"].any() else None
    weak_start   = data[~data["usd_regime"]]["날짜"].iloc[0] if (~data["usd_regime"]).any() else None
    label_y = data["us_eok"].max() * 0.88
    for dt, txt, bgcolor in [
        (strong_start, "📈 USD 강세", "#92400E"),
        (weak_start,   "📉 USD 약세", "#1E40AF"),
    ]:
        if dt is not None:
            fig.add_annotation(
                x=dt, y=label_y,
                text=f"<b>{txt}</b>",
                showarrow=False,
                font=dict(size=11, color=bgcolor),
                bgcolor="rgba(255,255,255,0.82)",
                bordercolor=bgcolor,
                borderwidth=1.2,
                borderpad=4,
                row=1, col=1,
            )

st.plotly_chart(fig, use_container_width=True)


# ── USD 강세/약세 구간별 알파 비교 ─────────────────────────────────────
if show_regime:
    st.subheader("📊 USD 강세 vs 약세 구간별 리라채 추가 효과")
    strong = data[data["usd_regime"]]
    weak   = data[~data["usd_regime"]]

    rc1, rc2, rc3 = st.columns(3)
    rc1.metric(
        f"🟡 USD 강세 구간 ({len(strong)}거래일)",
        f"{strong['alp_eok'].iloc[-1] if not strong.empty else 0:+.1f}억 누적",
        f"일평균 {strong['alp_eok'].diff().mean()*365/250:+.2f}억/년 페이스",
        delta_color="normal" if not strong.empty and strong["alp_eok"].mean() >= 0 else "inverse",
    )
    rc2.metric(
        f"🔵 USD 약세 구간 ({len(weak)}거래일)",
        f"{weak['alp_eok'].iloc[-1] if not weak.empty else 0:+.1f}억 누적",
        f"일평균 {weak['alp_eok'].diff().mean()*365/250:+.2f}억/년 페이스",
        delta_color="normal" if not weak.empty and weak["alp_eok"].mean() >= 0 else "inverse",
    )
    rc3.metric(
        "전체 기간 알파",
        f"{last['alp_eok']:+.1f}억",
        f"연환산 {last['alpha'] / last['t']:+.1f}%/년" if last["t"] > 0 else "",
        delta_color="normal" if last["alp_eok"] >= 0 else "inverse",
    )

st.divider()

# ── 수익 구조 설명 ─────────────────────────────────────────────────────
with st.expander("📐 수익 구성 요소 상세 (기간 말 기준)"):
    usdkrw_f  = last["usdkrw"]
    trykrw_f  = last["trykrw"]

    us_coupon_eok  = last["us_coupon_usd"] * usdkrw_f / usdkrw_0 * 100 * eok
    us_fx_eok      = (usdkrw_f - usdkrw_0) / usdkrw_0 * 100 * eok
    try_coupon_eok = last["try_coupon_try"] * trykrw_f / usdkrw_0 * 100 * eok
    try_fx_eok     = LEV_RATIO * usdtry_0 * (trykrw_f - trykrw_0) / usdkrw_0 * 100 * eok
    borrow_eok     = -(last["repay_krw"] - LEV_RATIO * usdkrw_0) / usdkrw_0 * 100 * eok

    rows = {
        "항목":   ["미국채 쿠폰",   "달러 환차손익",  "리라채 쿠폰",    "리라 환차손익",  "차입 비용(이자+환율)",  "합계"],
        "전략 A": [f"{us_coupon_eok:+.2f}억", f"{us_fx_eok:+.2f}억", "-", "-", "-", f"{last['us_eok']:+.2f}억"],
        "전략 B": [f"{us_coupon_eok:+.2f}억", f"{us_fx_eok:+.2f}억", f"{try_coupon_eok:+.2f}억", f"{try_fx_eok:+.2f}억", f"{borrow_eok:+.2f}억", f"{last['lev_eok']:+.2f}억"],
    }
    st.table(pd.DataFrame(rows).set_index("항목"))

    st.caption(
        f"진입 환율: USD/KRW {usdkrw_0:,.0f}  |  USD/TRY {usdtry_0:.2f}  |  TRY/KRW {trykrw_0:.2f}원\n"
        f"현재 환율: USD/KRW {usdkrw_f:,.0f}  |  TRY/KRW {trykrw_f:.2f}원  "
        f"(리라 {(trykrw_f/trykrw_0 - 1)*100:+.1f}%)"
    )

# ── 투자 조건 요약 ──────────────────────────────────────────────────────
with st.expander("📋 투자 조건 전체 요약"):
    st.markdown(f"""
| 항목 | 값 |
|---|---|
| 투자원금 | {scale_eok}억원 |
| USD 매입 규모 | ${usd_principal/1e6:.2f}M |
| 미국채 쿠폰 (진입시) | {us_c*100:.2f}% |
| USD 차입 규모 | ${usd_principal*LEV_RATIO/1e6:.2f}M |
| 차입 금리 | {loan_rate_pct:.1f}%/년 |
| 리라채 쿠폰 (진입시) | {try_c*100:.2f}% |
| TRY 매입 규모 | {usd_principal*LEV_RATIO*usdtry_0/1e6:.0f}M TRY |
| 경과 기간 | {last['t']*365:.0f}일 ({last['t']:.2f}년) |
    """)
