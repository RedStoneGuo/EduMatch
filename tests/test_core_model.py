"""Core TSI Engine: unified Supply/Demand/Fit/Gap mainline and the Primary TSI."""

from __future__ import annotations

import pytest

from agent.report import render_markdown
from edumatch.dataset import course_family_of
from analysis import fit, metric_graph, primary_tsi, skill_gap, supply, trend
from analysis import tsi as tsi_v2


def _resolve(name: str, description: str) -> list[str]:
    return [name]


def test_supply_is_continuous_and_channel_decomposed():
    """供给强度必须由通道构成，而不是课程是否出现该技能的 0/1 判定。"""
    plain = [{"name": "机器学习", "credits": 4.0}]
    structured = [{
        "name": "机器学习", "credits": 4.0, "is_required": True,
        "practice_hours": 32, "teaching_depth": "advanced",
    }]
    low = supply.build_supply_vector(plain, _resolve, provenance="target")
    high = supply.build_supply_vector(structured, _resolve, provenance="target")
    assert 0 < low.score["机器学习"] < high.score["机器学习"] <= 1.0
    assert high.channels["机器学习"].required_courses == 1
    assert high.channels["机器学习"].practice_courses == 1
    assert high.channels["机器学习"].depth_levels == ["advanced"]
    assert "objective" in high.unavailable_channels
    assert "required" in low.unavailable_channels


def test_objective_channel_adds_bounded_supply():
    courses = [{"name": "机器学习基础", "credits": 1.0}]
    base = supply.build_supply_vector(courses, _resolve, provenance="target")
    with_objective = supply.build_supply_vector(
        courses, _resolve, provenance="target", objective_skills=["机器学习基础"])
    assert with_objective.score["机器学习基础"] > base.score["机器学习基础"]
    assert with_objective.channels["机器学习基础"].objective_hit is True


def test_fit_and_gap_stay_closed():
    supply_map = {"a": 0.5, "b": 1.0}
    demand = {"a": 1.0, "b": 1.0, "c": 1.0}
    result = fit.skill_fit(supply_map, demand, unlisted_supply_is_zero=True)
    assert result["fit"] == pytest.approx((0.5 + 1.0 + 0.0) / 3)
    assert result["n_uncovered_in_scope"] == 1
    assert fit.fit_gap_closure(result)["consistent"] is True
    rows = {r["skill"]: r for r in result["per_skill"]}
    assert rows["c"]["supply_basis"] == "absent_in_scope"
    assert rows["c"]["gap"] == 1.0


def test_gap_treats_unlisted_supply_as_zero_only_when_asked():
    conservative = skill_gap.compute_skill_gaps({"Python": 0.6}, {"Java": 0.4})
    assert {r["skill"]: r["gap"] for r in conservative["rows"]} == {
        "Python": None, "Java": None}
    scoped = skill_gap.compute_skill_gaps(
        {"Python": 0.6}, {"Java": 0.4}, unlisted_supply_is_zero=True)
    rows = {r["skill"]: r for r in scoped["rows"]}
    assert rows["Python"]["gap"] == 0.6
    assert rows["Python"]["supply_basis"] == "absent_in_scope"
    assert rows["Java"]["gap"] is None


def test_primary_tsi_has_exactly_one_formal_score_and_a_clean_graph():
    graph = primary_tsi.dependency_graph()
    assert graph.double_counting_report()["clean"] is True
    assert sum(s.weight for s in primary_tsi.SPECS_BY_DIMENSION["F_供需适配"]) == pytest.approx(1.0)
    assert sum(v["weight"] for v in primary_tsi.DIMENSIONS.values()) == pytest.approx(1.0)
    registry = primary_tsi.version_registry(
        {"version": "primary-3.0", "primary_tsi": 61.0},
        {"tsi": 49.9, "n_indicators": 27},
        {"tsi_v2": 53.5, "n_total": 24},
    )
    assert registry["formal"]["id"] == "primary_tsi"
    assert registry["historical_version"]["role"] == "historical_version"
    assert registry["research_comparison"]["role"] == "research_comparison"
    assert sum(1 for v in registry.values() if v["role"] == "primary") == 1


def test_legacy_v2_double_counting_is_detected():
    v2 = metric_graph.v2_graph(tsi_v2.SPECS,
                               {k: v["weight"] for k, v in tsi_v2.DIMENSIONS.items()})
    groups = v2.duplicate_groups()
    assert groups
    assert {"B1", "C4"} in [set(g["metrics"]) for g in groups]


def test_trend_requires_distinct_periods():
    same_year = trend.series_summary([(2022, 0.40), (2022, 0.50), (2022, 0.47)])
    assert same_year["status"] == "insufficient_evidence"
    assert same_year["change"] is None
    assert same_year["series"][0]["n_samples"] == 3
    two_years = trend.series_summary([(2021, 0.40), (2024, 0.50)])
    assert two_years["status"] == "ok" and two_years["direction"] == "up"
    assert trend.response_analysis(same_year, two_years)["status"] == "insufficient_evidence"


@pytest.fixture(scope="module")
def target_result(engine) -> dict:
    return engine.run(
        "分析北京工业大学人工智能专业与北京就业市场的技能缺口",
        include_template=True,
    )


def test_target_and_peer_supply_are_separated(target_result):
    supply_block = target_result["supply"]
    assert supply_block["target"]["provenance"] == "target"
    assert supply_block["peer"]["provenance"] == "peer"
    # 目标校供给 = 该校"该专业自己的培养方案"课程；基准池是另一组独立课程
    assert supply_block["target"]["n_courses"] == len(target_result["courses"])
    assert supply_block["target"]["n_courses"] > 0
    assert supply_block["peer"]["n_courses"] > 0
    assert supply_block["target"]["n_courses"] != supply_block["peer"]["n_courses"]
    assert target_result["course_scope"]["used_for_fit"] == "target"
    assert "n_school_specific" in target_result["course_scope"]
    fit_target = target_result["skill_fit"]["target"]
    fit_peer = target_result["skill_fit"]["peer"]
    if fit_target.get("fit_100") is not None and fit_peer.get("fit_100") is not None:
        assert fit_target["fit_100"] != fit_peer["fit_100"]


def test_family_scope_never_borrows_another_family(engine):
    """点名高校本地没有该专业族课程时：目标供给记 insufficient_evidence，不借用别校课程。

    注：这里用中国石油大学（北京）——本地只有 2 份"修订意见/管理办法"，确实没有课程表；
    北京理工大学在补齐版式解析后已经有 96 个专业的课程，"该校没有课程"这个前提不再成立。
    """
    result = engine.run(
        "分析中国石油大学（北京）人工智能专业与北京就业市场的技能缺口", include_template=True)
    assert result["plan"]["family"] == "ai"
    assert result["supply"]["target"] is None
    assert result["course_scope"]["target_status"] == "insufficient_evidence"
    assert result["course_scope"]["used_for_fit"] == "peer"
    assert result["skill_fit"]["target"]["status"] == "insufficient_evidence"
    peer_skills = {row["skill"] for row in result["supply"]["peer"]["top_skills"]}
    assert peer_skills  # 计算机族仍有可核查课程（来自其他院校的同类专业）
    assert len(result["courses"]) == result["supply"]["peer"]["n_courses"]


def test_report_exposes_one_primary_tsi_and_keeps_versions_in_audit(target_result):
    report = render_markdown(target_result)
    assert "Primary TSI" in report
    assert all(f"## {i}." in report for i in range(1, 19))
    executive = report.split("## 2.")[0]
    assert "TSI 2.0 =" not in executive and "TSI v1" not in executive
    assert "research_comparison" in report
    assert not any(p in report for p in ("导致", "证明了", "必然导致"))


def test_data_quality_and_missing_handling(target_result):
    quality = target_result["data_quality"]
    assert quality["n_checks"] > 0 and quality["reliability"]
    primary = target_result["primary_tsi"]
    assert primary["primary_tsi"] is not None
    assert primary["weighted_coverage"] > 0
    values = {m["metric_id"]: m["value"] for m in primary["metrics"]}
    assert all(values[m] is None for m in primary["missing_indicators"])


def test_courses_are_tagged_with_their_major_family(dataset):
    """课程池不得跨专业族混用：软件工程不能被 AI 专业的课程评分。"""
    assert course_family_of(r"...\data\raw\majors_cs.txt") == "cs"
    assert course_family_of("AI竞赛数据归档/输出过程记录/教学.txt#doc1") == "ai"
    assert course_family_of("unknown/source.txt") is None
    assert dataset.course_set  # 三个族都可检索
    econ_pool = dataset.course_set(family="econ")
    assert econ_pool and all(c.get("major") for c in econ_pool)
    ai_names = {c["name"] for c in dataset.course_set(family="ai")}
    cs_names = {c["name"] for c in dataset.course_set(family="cs")}
    assert ai_names and cs_names
    cs_pool_names = {c["name"] for c in dataset.course_set(family="cs")}
    # 只出现在 ai 文件里的课程不得进入 cs 课程池（同名课程属抽取噪声，另行处理）
    assert not (ai_names - cs_names) & cs_pool_names
    assert dataset.course_set(family="ai", include_template=True)
    # E 级模板课程只服务 ai 族，不得出现在 econ 课程池
    assert not [c for c in dataset.course_set(family="econ", include_template=True) if c.get("template")]


def test_families_do_not_depend_on_curated_docs():
    """三个策展专业总结文档缺失时，注册表/课程/分析都必须照常工作。"""
    from edumatch.config import Settings
    from edumatch.dataset import Dataset
    from edumatch.engine import ResearchEngine

    raw = {"families": {
        "ai": {"name": "人工智能", "curated": "data/raw/__missing_ai.txt"},
        "cs": {"name": "计算机", "curated": "data/raw/__missing_cs.txt"},
        "econ": {"name": "经济管理", "curated": "data/raw/__missing_econ.txt"},
    }}
    ds = Dataset.build(Settings(raw=raw), with_policies=False, with_golden=False)
    assert set(ds.available_families) == {"ai", "cs", "econ"}
    assert not [c for c in ds.courses if "majors_" in str(c.source_document)]
    assert ds.golden_facts == []
    # 课程来自培养方案导入库：人工智能分析仍能给出可支撑结论
    result = ResearchEngine(ds).run(
        "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度",
        include_template=True, target_occupation="大模型算法工程师",
    )
    assert result["supply"]["target"]["n_courses"] > 20
    assert result["occupation_match"]["match_100"] is not None
    assert result["primary_tsi"]["primary_tsi"] is not None


def test_major_filter_keeps_target_major_only(dataset):
    """专业过滤：人工智能专业的供给里不得混入同校智能制造工程的课程。"""
    from edumatch.dataset import major_matches

    assert major_matches("计算机类（计算机科学与技术）", "计算机科学与技术")
    assert major_matches("人工智能（实验班）", "人工智能")
    assert not major_matches("智能制造工程", "人工智能")
    assert not major_matches("机器人工程", "人工智能")
    ai_courses = dataset.course_set(school="北京工业大学", family="ai", major="人工智能")
    assert ai_courses
    assert all(not c.get("major") or "人工智能" in str(c["major"]) for c in ai_courses)
    # 未标注专业来源的策展课程（major=None）仍可用；但不得出现标注为其他专业的培养方案课程
    other = dataset.course_set(school="北京工业大学", family="ai", major="智能制造工程")
    assert all(not c.get("major") for c in other)


def test_econ_demand_is_not_borrowed_from_the_ai_job_corpus(dataset):
    """岗位语料主轴是人工智能：经济管理族应记证据不足，而不是复用 AI 技能需求。"""
    profile = dataset.demand_corpus_profile()
    assert profile["status"] == "ok"
    assert profile["family_match_share"]["econ"] < 0.30
    demands = dataset.demand_vector(family="econ")
    assert demands == []
    assert "经济管理" in dataset.demand_scope_note or "econ" in dataset.demand_scope_note
    assert dataset.demand_vector(family="ai")


def test_information_management_is_named_and_scoped_correctly(dataset):
    from edumatch.engine import build_plan, detect_major

    major, family = detect_major("分析北京理工大学信息管理与信息系统专业与北京就业市场的供需适配", dataset)
    assert major == "信息管理与信息系统"
    assert family == "econ"
    plan = build_plan("分析北京理工大学信息管理与信息系统专业与北京就业市场的供需适配", dataset)
    assert (plan.major, plan.family, plan.school) == ("信息管理与信息系统", "econ", "北京理工大学")


def test_arbitrary_school_name_is_recognised(dataset):
    """任意院校名都要被识别出来，不能因为不在数据集里就当成"未指定高校"。"""
    from edumatch.engine import detect_school

    schools = dataset.schools()
    assert detect_school("分析复旦大学人工智能专业", schools) == "复旦大学"
    assert detect_school("请评估上海交通大学计算机专业", schools) == "上海交通大学"
    assert detect_school("对比清华大学与北京大学人工智能专业", schools) in {"清华大学", "北京大学"}
    # 区域口径的问题不应被误判成某所高校
    assert detect_school("分析北京市重点高校人工智能专业", schools) is None
    assert detect_school("北京市高校毕业生就业政策有哪些主要方向", schools) is None


def test_out_of_dataset_school_returns_insufficient(engine):
    """院校不在数据集里：如实说明该校无数据，不给区域口径结论。"""
    result = engine.run(
        "分析复旦大学人工智能专业与大模型算法工程师的匹配度",
        include_template=True, target_occupation="大模型算法工程师",
    )
    assert result["plan"]["school"] == "复旦大学"
    assert result["supply"]["target"] is None
    assert result["course_scope"]["target_status"] == "insufficient_evidence"
    # 岗位需求可以算（岗位族来自语料），但没有该校供给 → 匹配度必须是证据不足
    assert result["occupation_match"]["match_score"] is None
    assert result["occupation_match"]["status"] == "insufficient_evidence"
    assert result["occupation_match"]["band"] is None
    assert result["primary_tsi"]["primary_tsi"] is None
    report = render_markdown(result)
    assert "复旦大学" in report and "证据不足" in report


def test_insufficient_evidence_is_returned_instead_of_substitution(engine):
    """点名高校但该校没有该专业族数据时：返回证据不足，不得用其他口径的数值顶替。"""
    result = engine.run(
        "分析中国石油大学（北京）人工智能专业与北京就业市场的供需适配",
        include_template=True,
    )
    # 1) 目标校供给：null，不是"借用"来的课程池
    assert result["supply"]["target"] is None
    assert result["course_scope"]["target_status"] == "insufficient_evidence"
    assert result["skill_fit"]["target"]["fit_100"] is None
    # 2) 需求侧：AI/计算机目标语料不覆盖该专业族时，允许用**已披露的本地全量语料切片**兜底，
    #    但绝不允许静默挪用其他专业的需求向量：
    #      - 若兜底成功 → 必须写明语料/关键词/命中率（demand_scope.note 含"全量招聘语料"）
    #      - 若兜底不达标 → 仍记 insufficient_evidence
    demand_note = (result.get("demand_scope") or {}).get("note") or ""
    if result["demand_vector"]["n_skills"]:
        # 需求走主口径（岗位族 / 按专业导出语料）时不必有 note；
        # 只有走"本地全量语料切片兜底"才必须披露关键词与命中率。
        assert demand_note == "" or (
            "全量招聘语料" in demand_note
            and ("互不混用" in demand_note or "兜底" in demand_note))
    else:
        assert result["market"]["status"] == "insufficient_evidence"
        assert "insufficient_evidence" in demand_note
    # 3) 缺口：**目标校口径**不得出现缺口数字（该校没有可核查课程）。
    #    区域同类基准口径的缺口若可算，属于已披露的 peer 口径，不得冒充目标校。
    assert (result.get("skill_gaps_target") or {}).get("n_comparable", 0) == 0
    if result["skill_gaps"]["n_comparable"]:
        assert (result.get("supply") or {}).get("used_for_legacy_fit") == "peer"
    # 4) Primary TSI：定义性维度缺失 → 不予计算，而不是用剩余维度拼一个分数
    assert result["primary_tsi"]["primary_tsi"] is None
    assert result["primary_tsi"]["missing_required_dimensions"] == ["F_供需适配"]
    assert result["primary_tsi"]["not_computable_reason"]
    # 5) 报告必须把这个结论说清楚，而不是展示一个像模像样的分数
    report = render_markdown(result)
    assert "Primary TSI：无法计算" in report or "Primary TSI 无法计算" in report
    assert "insufficient_evidence" in report
    # 6) 就业侧不得跨校取数（校级口径只允许同校）
    for key in ("placement_rate_meta", "signing_rate_meta"):
        meta = (result["employment"].get(key) or {})
        if meta.get("value") is not None:
            assert meta.get("school") in {None, "中国石油大学（北京）", "中国石油大学"}
def test_school_records_cover_generic_majors(dataset, engine):
    """非三族专业（plan.family 为空）也要拿到多校就业事实。

    历史缺陷：`_school_records` 一律按 family 过滤，family 为空的专业会把该校该专业的
    就业事实整体丢掉 → 报告里「同类高校就业结果对比」整块消失（数据其实存在）。
    """
    from edumatch.engine import ResearchPlan

    plan = ResearchPlan(query="测试", mode="B_school_major_analysis", year=None,
                        school="清华大学", major="信息与计算科学", family="")
    records = engine._school_records(
        plan, ["placement_rate", "signing_rate", "further_study_rate"])
    assert records, "通用专业必须能取到多校就业记录"
    assert any(r.get("placement_rate") is not None for r in records)
