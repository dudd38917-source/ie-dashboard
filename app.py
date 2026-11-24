# IE Dashboard Streamlit App
import io
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="智能產線即時監控儀表板 (IE Dashboard)",
    page_icon="🏭",
    layout="wide",
)

st.title("🏭 智能椅子組裝產線即時監控儀表板")
st.caption("逢甲大學 工業工程與系統管理學系｜支援 IE Chair CSV 上傳、Cycle Time 與閒置時間驗算、四色燈號與 What-if 情境模擬")


def load_and_clean_csv(uploaded_file) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(uploaded_file)
    # 過濾掉 CSV 尾端摘要列，只保留有效工站作業紀錄
    valid_mask = raw["status"].isin(["COMPLETED", "IN_PROGRESS"]) & raw["station_id"].notna()
    df = raw[valid_mask].copy()
    footer = raw[~valid_mask].dropna(how="all")

    df["start_dt"] = pd.to_datetime(df["start_time"])
    df["finish_dt"] = pd.to_datetime(df["finish_time"])
    df["calc_duration_sec"] = (df["finish_dt"] - df["start_dt"]).dt.total_seconds()
    df["duration_sec"] = pd.to_numeric(df["duration_sec"], errors="coerce").fillna(df["calc_duration_sec"])
    df["wip_before_start"] = pd.to_numeric(df["wip_before_start"], errors="coerce").fillna(0)
    df["wip_after_finish"] = pd.to_numeric(df["wip_after_finish"], errors="coerce").fillna(0)
    return df, footer


def analyze_production(df: pd.DataFrame):
    line_start = df["start_dt"].min()
    line_end = df["finish_dt"].max()
    total_elapsed = (line_end - line_start).total_seconds()

    terminal_stations = df[df["station_flow"].astype(str).str.contains("終點", na=False)]["station_id"].unique().tolist()
    if not terminal_stations:
        terminal_stations = [sorted(df["station_id"].unique())[-1]]

    completed_output = df[
        (df["station_id"].isin(terminal_stations)) & (df["status"] == "COMPLETED")
    ]["product_id"].nunique()
    completed_output = max(1, completed_output)
    actual_line_ct = total_elapsed / completed_output

    rows = []
    for st_id, grp in df.groupby("station_id"):
        grp = grp.sort_values("start_dt")
        sum_dur = grp["duration_sec"].sum()
        sum_calc = grp["calc_duration_sec"].sum()
        avg_dur = grp["duration_sec"].mean()

        startup_idle = (grp["start_dt"].iloc[0] - line_start).total_seconds()
        tail_idle = (line_end - grp["finish_dt"].iloc[-1]).total_seconds()
        gaps = [
            max(0.0, (grp["start_dt"].iloc[i] - grp["finish_dt"].iloc[i - 1]).total_seconds())
            for i in range(1, len(grp))
        ]
        inter_job_idle = sum(gaps)
        total_idle = max(0.0, total_elapsed - sum_calc)

        valid_wip = grp[grp["wip_before_start"] < 9000]["wip_before_start"]
        is_raw_unlimited = len(valid_wip) == 0
        max_wip = float(valid_wip.max()) if not is_raw_unlimited else 0.0

        rows.append({
            "工作站": st_id,
            "流程位置": grp["station_flow"].iloc[0],
            "完工次數": len(grp),
            "總加工時間(秒)": round(sum_dur, 2),
            "平均 Cycle Time(秒)": round(avg_dur, 2),
            "最短(秒)": round(grp["duration_sec"].min(), 2),
            "最長(秒)": round(grp["duration_sec"].max(), 2),
            "開工前等料(秒)": round(startup_idle, 2),
            "件間等待空檔(秒)": round(inter_job_idle, 2),
            "收尾閒置(秒)": round(tail_idle, 2),
            "總閒置時間(秒)": round(total_idle, 2),
            "稼動率(%)": round(sum_calc / total_elapsed * 100, 1),
            "站前最大WIP": max_wip,
            "原料充足": is_raw_unlimited,
        })

    st_df = pd.DataFrame(rows).sort_values("工作站").reset_index(drop=True)
    bottleneck_ct = st_df["平均 Cycle Time(秒)"].max()
    st_df["每週期平衡閒置(秒)"] = (bottleneck_ct - st_df["平均 Cycle Time(秒)"]).round(2)

    bottleneck_st = st_df.loc[st_df["平均 Cycle Time(秒)"].idxmax(), "工作站"]
    fastest_st = st_df.loc[st_df["平均 Cycle Time(秒)"].idxmin(), "工作站"]
    fastest_ct = st_df["平均 Cycle Time(秒)"].min()
    sum_avg_ct = st_df["平均 Cycle Time(秒)"].sum()
    line_balance = sum_avg_ct / (len(st_df) * bottleneck_ct) * 100
    theo_tp = 3600 / bottleneck_ct
    actual_tp = completed_output / (total_elapsed / 3600)

    summary = {
        "group_id": df["group_id"].iloc[0],
        "round_id": df["round_flow_id"].iloc[0],
        "total_elapsed": total_elapsed,
        "completed_output": completed_output,
        "actual_line_ct": actual_line_ct,
        "bottleneck_st": bottleneck_st,
        "bottleneck_ct": bottleneck_ct,
        "fastest_st": fastest_st,
        "fastest_ct": fastest_ct,
        "line_balance": line_balance,
        "theo_tp": theo_tp,
        "actual_tp": actual_tp,
        "terminal_stations": terminal_stations,
    }
    return st_df, summary


# 側邊欄上傳與參數
with st.sidebar:
    st.header("📂 資料上傳與警戒設定")
    uploaded_file = st.file_uploader("上傳 IE Chair CSV 檔案", type=["csv"])
    st.divider()
    wip_thresh = st.number_input("🟡 WIP 堆積警戒門檻 (件)", min_value=1, value=3, step=1)
    idle_ratio = st.slider("🔵 空閒站判定 (低於瓶頸 %)", 30, 90, 75, 5) / 100.0
    target_tp = st.number_input("🎯 每小時目標產量 (件/時)", min_value=5, value=80, step=5)

if uploaded_file is None:
    st.info("👈 請先從左側欄上傳 IE Chair 匯出的 CSV 檔案（例如 `ie_chair_data_G16 2.csv` 或正式實作 9 站 CSV）。")
    st.stop()

df, footer = load_and_clean_csv(uploaded_file)
st_df, summary = analyze_production(df)

with st.sidebar:
    warn_line = st.number_input(
        "🔴 瓶頸警戒線 (秒)",
        min_value=1.0,
        value=float(round(summary["bottleneck_ct"] * 0.9, 1)),
        step=1.0,
    )

# 判定四色燈號
def classify_status(row):
    if row["工作站"] == summary["bottleneck_st"] or row["平均 Cycle Time(秒)"] >= warn_line:
        return "🔴 紅燈：瓶頸站"
    if (not row["原料充足"]) and row["站前最大WIP"] >= wip_thresh:
        return "🟡 黃燈：WIP 堆積"
    if row["平均 Cycle Time(秒)"] <= summary["bottleneck_ct"] * idle_ratio:
        return "🔵 藍燈：空閒可支援"
    return "🟢 綠燈：正常"

st_df["燈號狀態"] = st_df.apply(classify_status, axis=1)

# 即時警示
st.error(
    f"🚨 【即時警示】組別 {summary['group_id']}｜最慢瓶頸站為 **{summary['bottleneck_st']}（{summary['bottleneck_ct']:.2f} 秒）**！"
    f"建議將最空閒的 **{summary['fastest_st']}（{summary['fastest_ct']:.2f} 秒）** 人員調往支援。"
)

# 四大 KPI 卡片
c1, c2, c3, c4 = st.columns(4)
c1.metric("全線實際 Cycle Time", f"{summary['actual_line_ct']:.2f} 秒/組", f"總耗時 {summary['total_elapsed']:.1f}s ÷ {summary['completed_output']} 組")
c2.metric("瓶頸站 Cycle Time", f"{summary['bottleneck_ct']:.2f} 秒/組", f"瓶頸：{summary['bottleneck_st']}")
c3.metric("實測每小時產出量", f"{summary['actual_tp']:.1f} 件/時", f"目標 {target_tp} 件/時")
c4.metric("產線平衡率", f"{summary['line_balance']:.1f}%", f"理論極限 {summary['theo_tp']:.1f} 件/時")

tab1, tab2, tab3, tab4 = st.tabs(["🚦 戰情看板 & Cycle Time", "⏱️ 各站閒置時間", "🔄 What-if 跨站模擬", "📐 6 大生產指標 & 驗算"])

with tab1:
    st.subheader("工站四色狀態燈號")
    cols = st.columns(min(4, len(st_df)))
    for i, row in st_df.iterrows():
        with cols[i % len(cols)]:
            wip_txt = "原料充足" if row["原料充足"] else f"最大 WIP: {int(row['站前最大WIP'])} 件"
            st.info(f"**{row['工作站']}**｜{row['平均 Cycle Time(秒)']} 秒\n\n{row['燈號狀態']}\n\n完工 {row['完工次數']} 件｜{wip_txt}")

    st.subheader("各工作站平均作業時間長條圖")
    color_map = {"🔴 紅燈：瓶頸站": "#dc2626", "🟡 黃燈：WIP 堆積": "#d97706", "🔵 藍燈：空閒可支援": "#2563eb", "🟢 綠燈：正常": "#64748b"}
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=st_df["工作站"],
        y=st_df["平均 Cycle Time(秒)"],
        marker_color=[color_map[s] for s in st_df["燈號狀態"]],
        text=st_df["平均 Cycle Time(秒)"].map(lambda v: f"{v:.1f}s"),
        textposition="outside",
    ))
    fig.add_hline(y=warn_line, line_dash="dash", line_color="red", annotation_text=f"瓶頸警戒線 ({warn_line}s)")
    fig.update_layout(yaxis_title="平均作業時間 (秒)", height=400)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(st_df[["工作站", "流程位置", "完工次數", "總加工時間(秒)", "平均 Cycle Time(秒)", "最短(秒)", "最長(秒)", "燈號狀態"]], use_container_width=True)

with tab2:
    st.subheader("各工作站加工時間 vs. 閒置時間拆解")
    fig_idle = go.Figure()
    fig_idle.add_trace(go.Bar(name="總加工時間", x=st_df["工作站"], y=st_df["總加工時間(秒)"], marker_color="#2563eb"))
    fig_idle.add_trace(go.Bar(name="開工前等料", x=st_df["工作站"], y=st_df["開工前等料(秒)"], marker_color="#f59e0b"))
    fig_idle.add_trace(go.Bar(name="件間等待空檔", x=st_df["工作站"], y=st_df["件間等待空檔(秒)"], marker_color="#ef4444"))
    fig_idle.add_trace(go.Bar(name="收尾閒置", x=st_df["工作站"], y=st_df["收尾閒置(秒)"], marker_color="#94a3b8"))
    fig_idle.update_layout(barmode="stack", yaxis_title="秒數 (sec)", height=380)
    st.plotly_chart(fig_idle, use_container_width=True)
    st.dataframe(st_df[["工作站", "總加工時間(秒)", "開工前等料(秒)", "件間等待空檔(秒)", "收尾閒置(秒)", "總閒置時間(秒)", "稼動率(%)", "每週期平衡閒置(秒)"]], use_container_width=True)

with tab3:
    st.subheader("What-if 跨站人力支援模擬")
    w1, w2, w3 = st.columns(3)
    st_list = st_df["工作站"].tolist()
    helper_st = w1.selectbox("🔵 派出支援站", st_list, index=st_list.index(summary["fastest_st"]))
    target_st = w2.selectbox("🔴 接受支援瓶頸站", st_list, index=st_list.index(summary["bottleneck_st"]))
    reduce_pct = w3.slider("⚡ 瓶頸工時縮短比例 (%)", 5, 50, 25)

    sim_df = st_df[["工作站", "平均 Cycle Time(秒)"]].copy()
    sim_df.loc[sim_df["工作站"] == target_st, "平均 Cycle Time(秒)"] *= (1 - reduce_pct / 100.0)
    new_max = sim_df["平均 Cycle Time(秒)"].max()
    new_bn = sim_df.loc[sim_df["平均 Cycle Time(秒)"].idxmax(), "工作站"]
    new_tp = 3600 / new_max
    new_bal = sim_df["平均 Cycle Time(秒)"].sum() / (len(sim_df) * new_max) * 100

    m1, m2, m3 = st.columns(3)
    m1.metric("改善後最慢瓶頸時間", f"{new_max:.2f} 秒", f"{new_max - summary['bottleneck_ct']:.2f} 秒 (新瓶頸 {new_bn})", delta_color="inverse")
    m2.metric("改善後理論每小時產出", f"{new_tp:.1f} 件/時", f"+{((new_tp - summary['theo_tp']) / summary['theo_tp'] * 100):.1f}%")
    m3.metric("改善後產線平衡率", f"{new_bal:.1f}%", f"{new_bal - summary['line_balance']:+.1f}%")

with tab4:
    st.subheader("課後練習：6 大生產指標")
    p1, p2, p3, p4 = st.columns(4)
    plan_out = p1.number_input("目標產量 (組)", min_value=1, value=summary["completed_output"] + 1)
    std_time = p2.number_input("單站標準工時 (秒)", min_value=1.0, value=20.0)
    defects = p3.number_input("不良品件數 (組)", min_value=0, value=0)
    workers_per_st = p4.number_input("每站人數 (人)", min_value=1, value=1)

    out = summary["completed_output"]
    attainment = out / plan_out * 100
    ontime_rate = (df["duration_sec"] <= std_time).mean() * 100
    fpy = max(0, out - defects) / out * 100
    emp_prod = out / (len(st_df) * workers_per_st * (summary["total_elapsed"] / 3600))

    k1, k2, k3 = st.columns(3)
    k1.metric("1. Production Output 生產產量", f"{out} 組")
    k2.metric("2. Production Attainment 達成率", f"{attainment:.1f}%")
    k3.metric("3. On-Time Completion 準時完成率", f"{ontime_rate:.1f}%")
    k4, k5, k6 = st.columns(3)
    k4.metric("4. First Pass Yield 首次通過率", f"{fpy:.1f}%")
    k5.metric("5. Cycle Time 週期時間", f"{summary['actual_line_ct']:.2f} 秒/組")
    k6.metric("6. Employee Productivity 員工生產力", f"{emp_prod:.1f} 件/人時")

    st.divider()
    st.subheader("原始有效紀錄（供手動驗算）")
    st.dataframe(df[["product_id", "station_id", "start_time", "finish_time", "duration_sec", "calc_duration_sec", "wip_before_start"]], use_container_width=True)
    if not footer.empty:
        st.caption("原 CSV 尾端內建摘要（已自動過濾，僅供對照驗算）：")
        st.dataframe(footer, use_container_width=True)
