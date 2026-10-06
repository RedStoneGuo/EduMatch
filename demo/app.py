"""EduMatch Streamlit demo.

    streamlit run demo/app.py

Every panel is driven by the same ResearchEngine output that the CLI and MCP
tools use, so the demo cannot drift from the computed numbers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core import TalentSupplyDemandAgent  # noqa: E402

DEFAULT_QUERY = (
    "分析北京市重点高校人工智能专业与 2025 年 AI 招聘市场的人才供需适配情况，"
    "并找出最关键的技能缺口。"
)

st.set_page_config(page_title="EduMatch｜高校人才供需适配研究 Agent", layout="wide")


@st.cache_resource(show_spinner="正在载入归档数据与技能本体…")
def get_agent() -> TalentSupplyDemandAgent:
    return TalentSupplyDemandAgent()


def run_research(query: str, include_template: bool, simulate: bool) -> dict:
    agent = get_agent()
    result = agent.research(query, include_template=include_template, simulate=simulate)
    return result.to_dict()


st.title("EduMatch｜高校人才供需适配研究 Agent")
st.caption("从培养方案到就业市场的智能供需诊断与培养优化 · Evidence-driven · 可复现")

with st.sidebar:
    st.header("研究任务")
    query = st.text_area("研究问题", value=DEFAULT_QUERY, height=120)
    include_template = st.checkbox(
        "纳入模板课程（E 级证据）", value=True,
        help="档案中可核查课程仅 22 门；模板课程用于演示完整链路，结果中会明确标注。",
    )
    simulate = st.checkbox("运行培养方案模拟", value=True)
    submitted = st.button("开始研究", type="primary", use_container_width=True)
    st.divider()
    st.caption("LLM 只负责解释；所有数值由 analysis/ 下的纯函数计算，缺失记 null。")

if submitted or "result" not in st.session_state:
    with st.spinner("Agent 正在执行研究计划：检索证据 → 归一化技能 → 计算匹配与缺口 …"):
        st.session_state["result"] = run_research(query, include_template, simulate)

data = st.session_state["result"]
plan, tsi, matching, gaps = data["plan"], data["tsi_v2"], data["matching"], data["skill_gaps"]
primary = data.get("primary_tsi") or {}
target_fit = (data.get("skill_fit") or {}).get("target") or {}

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Primary TSI（正式）", primary.get("primary_tsi"), primary.get("band") or "")
c2.metric("Skill Fit（目标校口径）", f"{matching['matching_score_100']}/100",
          (data.get("course_scope") or {}).get("used_for_fit") or "")
c3.metric("Skill Gap Index", gaps["skill_gap_index"])
c4.metric("主指标覆盖率", f"{(primary.get('weighted_coverage') or 0) * 100:.0f}%",
          f"TSI 2.0 {tsi['tsi_v2']}（研究对照）")
c5.metric("证据条目", len(data["evidence"]))
if target_fit.get("partial_supply"):
    st.warning("目标高校可核查课程少于门槛：供需适配维为证据保守下界，"
               "同类基准（北京同类专业）与市场需求另列对照，未替代目标校口径。")

tabs = st.tabs([
    "① 研究任务", "② 工作流状态", "③ 数据证据", "④ 专业画像", "⑤ 岗位画像",
    "⑥ 技能匹配", "⑦ Skill Gap", "⑧ TSI 2.0", "⑨ 机制分析", "⑩ 方案模拟",
    "⑪ Evidence Chain", "⑫ 完整报告",
])

with tabs[0]:
    st.subheader("任务理解与规划")
    st.write(f"**研究问题**：{data['query']}")
    st.write(f"**识别模式**：`{data['mode']}`　**专业**：{plan['major']}　"
             f"**学校**：{plan['school'] or '北京 211 同类专业样本'}　**年份**：{plan['year']}")
    st.dataframe(pd.DataFrame(plan["steps"]), use_container_width=True)

with tabs[1]:
    st.subheader("Agent 工具调用链")
    calls = pd.DataFrame(data["tool_calls"])
    st.dataframe(calls[["tool", "status", "elapsed_ms", "arguments"]], use_container_width=True)
    st.caption(f"共 {len(calls)} 次工具调用；全部状态 ok 才会输出结论。")
    st.json({"skill_calls": data["skill_calls"]}, expanded=False)

with tabs[2]:
    st.subheader("数据范围与证据")
    st.json(data["dataset_summary"])
    st.dataframe(pd.DataFrame(data["evidence"])[
        ["evidence_id", "source_type", "evidence_level", "title", "locator", "confidence"]
    ], use_container_width=True)

with tabs[3]:
    st.subheader("供给侧画像")
    rows = []
    for key, label in (("practice_credit_ratio", "实践学分占比"), ("senior_title_ratio", "高级职称比例"),
                       ("student_faculty_ratio", "生师比"), ("training_base_count", "实习实训基地数")):
        meta = data["teaching"].get(f"{key}_meta") or {}
        rows.append({"指标": label, "值": data["teaching"].get(key), "年份": meta.get("year"),
                     "样本": meta.get("n"), "状态": meta.get("status"), "来源": meta.get("source_document")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    st.info((data.get("course_scope") or {}).get("reason") or "课程证据为学校级。")
    st.dataframe(pd.DataFrame(data["courses"])[
        ["name", "credits", "category", "is_practice", "template", "school", "source_document"]
    ], use_container_width=True)

with tabs[4]:
    st.subheader("需求侧画像")
    st.json({k: data["market"][k] for k in
             ("counts_status", "raw_count", "deduplicated_count", "effective_count",
              "skill_demand_mean", "emerging_skill_share", "confidence", "note")})
    demand_df = pd.DataFrame(matching["per_skill"]).head(15).set_index("skill")
    st.bar_chart(demand_df[["demand"]])
    st.dataframe(demand_df, use_container_width=True)

with tabs[5]:
    st.subheader("课程—技能—岗位匹配")
    st.write(f"匹配度 **{matching['matching_score_100']}/100**，广度召回 "
             f"{matching.get('recall')}，Jaccard {matching.get('jaccard')}")
    matrix = data["course_skill_matrix"]
    frame = pd.DataFrame(matrix["matrix"], index=matrix["course_ids"], columns=matrix["skills"])
    st.dataframe(frame, use_container_width=True, height=320)
    col1, col2 = st.columns(2)
    col1.success("已覆盖需求技能：" + "、".join(matching.get("matched_skills") or []))
    col2.warning("未覆盖需求技能：" + "、".join(matching.get("unmet_demand_skills") or []))

with tabs[6]:
    st.subheader("Skill Gap")
    gap_df = pd.DataFrame(gaps["rows"])
    st.dataframe(gap_df[["skill", "demand", "supply", "gap", "status", "severity",
                         "confidence", "evidence_level"]], use_container_width=True)
    cross = gaps.get("reported_gap_crosscheck") or {}
    if cross.get("rows"):
        st.markdown("**与归档旧结论的交叉核对**")
        st.dataframe(pd.DataFrame(cross["rows"]), use_container_width=True)

with tabs[7]:
    st.subheader("TSI 2.0 四维分解")
    st.dataframe(pd.DataFrame(tsi["dimensions"]).T, use_container_width=True)
    st.bar_chart(pd.DataFrame({
        "维度": [v["name"] for v in tsi["dimensions"].values()],
        "得分": [v["score"] for v in tsi["dimensions"].values()],
    }).set_index("维度"))
    st.warning("缺失指标（记 null，不记 0）：" + (", ".join(tsi["missing_indicators"]) or "无"))
    if data.get("legacy_comparison"):
        st.markdown("**与旧版 Coze 逻辑对比**")
        st.json(data["legacy_comparison"])

with tabs[8]:
    st.subheader("机制分析")
    st.json(data["mechanism"])
    st.caption("表述已通过因果语言护栏：只描述关联与解释贡献，不做因果断言。")

with tabs[9]:
    st.subheader("培养方案模拟")
    sim = data.get("simulation")
    if not sim:
        st.info("未启用模拟：在侧栏勾选『运行培养方案模拟』。")
    else:
        c = sim["combined_scenario"]
        col1, col2, col3 = st.columns(3)
        col1.metric("TSI 变化", c.get("tsi_delta"), f"{c.get('tsi_before')} → {c.get('tsi_after')}")
        col2.metric("匹配度变化", c.get("matching_delta"))
        col3.metric("缺口收敛技能数", len([g for g in c["gaps_changed"] if g["change"] < 0]))
        st.dataframe(pd.DataFrame(c["gaps_changed"]), use_container_width=True)
        st.error(sim["disclaimer"])
        st.markdown("**模型假设**")
        for a in sim["assumptions"]:
            st.markdown(f"- {a}")

with tabs[10]:
    st.subheader("Evidence Chain")
    st.dataframe(pd.DataFrame(data["evidence"])[
        ["evidence_id", "evidence_level", "source_type", "title", "locator", "quote"]
    ], use_container_width=True, height=420)

with tabs[11]:
    st.subheader("完整研究报告")
    st.markdown(data["report"])
    st.download_button("下载 Markdown 报告", data["report"].encode("utf-8"),
                       file_name=f"{data['run_id'].replace(':', '_')}.md")
    st.download_button("下载完整 JSON", json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name=f"{data['run_id'].replace(':', '_')}.json")
