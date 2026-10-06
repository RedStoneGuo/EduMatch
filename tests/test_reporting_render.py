"""Core 报告交付层：主题/构件可复用，任意院校专业按层级渲染且只含所选层级。"""

from __future__ import annotations

import reporting
from reporting import components as C
from reporting.render import render_result
from reporting.theme import CSS, JS


def _result() -> dict:
    return {
        "run_id": "run:test",
        "plan": {"school": "北京工业大学", "major": "信息管理与信息系统"},
        "primary_tsi": {
            "primary_tsi": 58.2, "band": "基本适配", "weighted_coverage": 0.9,
            "missing_indicators": ["S1", "M3"],
            "dimensions": {"F_供需适配": {"score": 61.0}, "S_培养基础": {"score": 55.0},
                           "O_人才结果": {"score": 60.0}, "M_需求背景": {"score": 40.0}},
            "metrics": [{"metric_id": "F1", "name": "技能适配度", "value": 61.0,
                         "status": "ok", "evidence_level": "C"}],
        },
        "supply": {"target": {"n_courses": 75, "n_mapped_courses": 50, "reliability": "medium",
                              "top_skills": [{"skill": "Python", "supply": 0.6}]},
                   "used_for_legacy_fit": "target"},
        "demand_rows": [{"skill": "Python", "demand": 0.5}, {"skill": "SQL", "demand": 0.4}],
        "skill_gaps": {"rows": [{"skill": "SQL", "demand": 0.4, "supply": 0.0, "gap": 0.4,
                                 "status": "gap", "supply_basis": "absent_in_scope"}]},
        "occupation": {"occupation": {"name": "数据分析师"}, "n_jobs": 1508,
                       "match_scope": "position"},
        "occupation_match": {"match_100": 52.0, "band": "部分匹配"},
        "skill_gaps_target": {"rows": [{"skill": "SQL", "demand": 0.4, "supply": 0.0,
                                        "gap": 0.4, "status": "gap"}]},
        "semantic": {"objective_job_alignment": {"similarity": None, "status": "insufficient_evidence",
                                                 "notes": "未找到本专业培养目标原文"}},
        "coverage": {"n_schools": 3},
        "retrieval_ledger": {"materials": {"培养目标": {"attempts": [
            {"kind": "pdf_text", "state": "hit", "reason": "正文可读但未找到本专业目标"}]}},
            "summary": {"n_attempts": 1, "n_hits": 1, "needs_online": {"培养目标": True}}},
        "micro_result": {
            "sparse_level": 3, "fit_100": 61.0, "supply_provenance": "personal_evidence",
            "gaps": {"knowledge": {"status": "ok", "n_gap": 0, "top_gaps": []},
                     "skill": {"status": "ok", "n_gap": 1,
                               "top_gaps": [{"item": "SQL", "gap": 0.4}]},
                     "capability": {"status": "insufficient_evidence", "reason": "缺需求向量"},
                     "practice": {"status": "insufficient_evidence", "reason": "缺需求向量"}},
            "priority_actions": [{"layer": "skill", "action": "补齐 SQL 并留可核查产出"}],
        },
    }


def test_theme_and_components_are_reusable_assets():
    assert ":root{" in CSS and "scalenav" in CSS
    assert "addEventListener" in JS
    assert C.nav_html("macro").count('href="#') >= 2
    assert "#macro" in C.nav_html("macro") and "#meso" not in C.nav_html("macro")
    # 顶栏必须锁死单行：副标题超出省略号，且不再渲染上下文小字
    assert "text-overflow:ellipsis" in CSS and "white-space:nowrap" in CSS
    assert "sn-context" not in C.nav_html("all", context="某院校 · 某专业")


def test_render_result_only_contains_selected_scope():
    result = _result()
    meso = render_result(result, "meso")
    assert 'id="meso"' in meso and 'id="macro"' not in meso and 'id="micro"' not in meso
    # 单层级不渲染总览（总览天然是三视图），但门卡与来源仍在
    assert 'id="overview"' not in meso
    assert 'class="doors"' in meso and 'id="source"' in meso
    assert "数据分析师" in meso and "个人证据画像" not in meso
    micro = render_result(result, "micro")
    assert 'id="micro"' in micro and 'id="macro"' not in micro
    assert "SQL" in micro and "区域供给" not in micro
    full = render_result(result, "all")
    for marker in ('id="macro"', 'id="meso"', 'id="micro"'):
        assert marker in full
    for marker in ('id="overview"', 'class="ladder"', 'id="compare"', 'class="doors"'):
        assert marker in full


def test_render_uses_official_layout_not_ad_hoc_css():
    html = render_result(_result(), "all")
    assert "--ink:#141414" in html and ":root{" in html   # 主题来自 reporting.theme
    assert 'class="scalenav"' in html
    assert 'class="tsi-grid"' in html
    assert "全面检索台账" in html


def test_only_cover_is_active_and_sections_are_switchable():
    """路由契约：只有 #cover 带 on；其余视图是 .view —— 否则子页会重复渲染封面。"""
    html = render_result(_result(), "all")
    assert html.count('class="view on"') == 1
    assert '<section class="view on" id="cover">' in html
    for view in ("overview", "macro", "meso", "micro", "source"):
        assert f'<section class="view" id="{view}"' in html
    assert html.count("<section") == html.count("</section>")


def test_nav_has_scope_context_and_doors_are_labelled():
    html = render_result(_result(), "all")
    # 顶栏只保留层级+极短副标题；院校/专业/岗位那行小字已删除（它会把顶栏顶宽顶高）
    nav = html[html.index('<nav class="scalenav"'):html.index("</nav>")]
    assert "sn-context" not in nav
    assert "scope=all" not in nav and "数据分析师" not in nav
    for label in ("宏观 · 政府端", "中观 · 专业", "微观 · 个人"):
        assert label in html
    # 封面门卡的分数单位不能因为文案过长而换行
    cover = html[html.index('id="cover"'):html.index('id="overview"')]
    assert "（子指标）" not in cover
    assert "/100 目标岗位适配" in html and "/100 个人岗位适配" in html


def test_nav_subs_reflect_the_current_subject():
    result = _result()
    result["supply"]["peer_by_school"] = [{"school": "同类院校甲", "n_courses": 10}]
    result["supply"]["peer_n_schools"] = 1
    html = render_result(result, "macro")
    assert "信息管理与信息系统" in html
    nav = html[html.index('<nav class="scalenav"'):html.index("</nav>")]
    assert "区域 · 1 所高校" in nav            # 宏观副标题=本次范围（简短）
    html_all = render_result(result, "all")
    nav_all = html_all[html_all.index('<nav class="scalenav"'):html_all.index("</nav>")]
    assert "北京工业大学 · 信息管理与信息系统" in nav_all   # 中观副标题=本次院校专业
    assert "证据分层 L3" in nav_all            # 微观副标题=本次证据分层


def test_scale_titles_are_generated_from_this_report():
    """三层子页大标题必须按当次分析对象生成，不能是死模板句。"""
    result = _result()
    result["supply"]["target"]["n_courses"] = 75
    result["supply"]["peer"] = {"n_courses": 380}
    result["supply"]["peer_by_school"] = [{"school": "同类院校甲", "n_courses": 260}]
    result["supply"]["peer_n_schools"] = 1
    html = render_result(result, "all")
    for marker in ("信息管理与信息系统相关培养能力", "覆盖 1 所院校", "380 门课程池",
                   "北京工业大学 · 信息管理与信息系统 培养方案", "75 门可核查课程",
                   "数据分析师", "个人证据画像（L3）"):
        assert marker in html, f"标题缺少本次分析信息：{marker}"
    for dead in ("区域供给（覆盖高校样本）", "专业培养方案<br>× 目标岗位",
                 "个人证据画像<br>→ 个性化补齐"):
        assert dead not in html, f"死模板句仍在：{dead}"


def test_nav_subs_escape_markup_in_school_and_major():
    """校名/专业名要转义：零数据模板的占位是 <院校>，不转义会被浏览器当标签吞掉。"""
    result = _result()
    result["plan"]["school"] = "<院校>"
    result["plan"]["major"] = "<专业>"
    html = render_result(result, "all")
    nav = html[html.index('<nav class="scalenav"'):html.index("</nav>")]
    assert "&lt;院校&gt; · &lt;专业&gt;" in nav
    assert "<院校>" not in nav


def test_dimensions_never_vanish_when_data_is_missing():
    """缺数据时维度必须显示「未获取」，不能整块消失——这是交付验收标准。"""
    result = _result()
    result["benchmark"] = {}          # 本地没有该校该专业的就业事实
    result["micro_result"] = {}       # 本轮没有个人画像
    html = render_result(result, "all")
    for marker in ("同类高校就业结果对比", "不估算、不用别的专业顶替",
                   "个人缺口 · 岗位需求 vs 个人供给", "优先行动",
                   "本轮没有个人画像输入"):
        assert marker in html, f"缺数据时维度消失：{marker}"


def test_titles_use_the_real_demand_basis():
    """岗位族没解析成功、但需求来自专业导出语料时，标题要按真实口径措辞。"""
    result = _result()
    result["occupation"]["status"] = "insufficient_evidence"
    result["occupation"]["demand_status"] = "insufficient_evidence"
    result["occupation"]["n_jobs"] = 0
    result["occupation"]["occupation"] = {"requested": "会计", "name": None}
    result["demand_scope"] = {"coverage": {"label": "会计学", "n_jobs": 933,
                                           "keyword_source": "major_export"}}
    html = render_result(result, "macro")
    assert "会计学 专业需求语料" in html
    assert "可观察岗位招聘记录 933 条" in html
    assert "岗位族未命中，但需求侧有数据" in html


def test_bars_never_exceed_full_width():
    html = render_result(_result(), "all")
    widths = [float(m.group(1)) for m in __import__("re").finditer(r"width:([0-9.]+)%", html)]
    assert widths and max(widths) <= 100.01


def test_micro_page_has_full_structure():
    html = render_result(_result(), "micro")
    for marker in ("个人证据画像明细", "四层缺口全量明细", "优先行动", "证据分层"):
        assert marker in html


def test_lazy_export_is_available():
    assert callable(reporting.render_result)


def _template_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "reporting" / "templates"


def test_page_template_contains_no_real_data():
    """模板必须是零真实数据的骨架：不能带任何案例院校/专业/数值。"""
    html = (_template_dir() / "page_template.html").read_text(encoding="utf-8")
    for leaked in ("北京工业大学", "人工智能", "大模型算法工程师", "北工大",
                   "16,161", "16161", "61.07", "信息管理与信息系统"):
        assert leaked not in html, f"模板泄漏真实数据：{leaked}"
    for marker in ('id="macro"', 'id="meso"', 'id="micro"', 'id="source"',
                   "零真实数据的报告模板", "目标岗位画像", "全面检索台账", "未获取",
                   'class="doors"', 'class="door gov"', 'class="door tea"', 'class="door stu"',
                   'id="overview"', 'class="ladder"', 'class="rung"', 'id="compare"',
                   "cmp-tbl", 'class="refs"', 'sup class="ref"', "回到引用处",
                   "怎么读这张图"):
        assert marker in html, f"模板缺少结构：{marker}"


def test_micro_template_is_single_scope_and_clean():
    html = (_template_dir() / "page_template_micro.html").read_text(encoding="utf-8")
    assert 'id="micro"' in html and 'id="macro"' not in html and 'id="meso"' not in html
    assert "北京工业大学" not in html and "北工大" not in html


def test_macro_enumerates_every_school_as_an_information_source():
    """宏观必须逐校列出信息源——不能只显示 1 所高校，也不能只给一个校名。"""
    result = _result()
    result["supply"].update({
        "target_by_school": [{"school": "北京工业大学", "n_courses": 75}],
        "peer_by_school": [{"school": "同类院校甲", "n_courses": 260},
                           {"school": "同类院校乙", "n_courses": 120}],
        "peer": {"n_courses": 380, "top_skills": [{"skill": "Python", "supply": 1.0}]},
        "peer_n_schools": 2,
    })
    result["benchmark"] = {"education_background": {"entities": [
        {"entity": "同类院校甲", "placement_rate": 0.95, "further_study_rate": 0.4},
        {"entity": "北京工业大学", "placement_rate": 0.93, "further_study_rate": 0.5},
    ]}}
    html = render_result(result, "macro")
    assert "宏观信息源 · 覆盖院校台账" in html
    for school in ("同类院校甲", "同类院校乙", "北京工业大学"):
        assert school in html, f"台账缺院校：{school}"
    # 统计卡必须报"区域课程池院校"，不能把覆盖样本写成 1 所目标校
    assert "区域课程池院校" in html
    assert "本地入库覆盖高校" not in html
    # 多校就业结果要真的逐校画出来
    assert "各校毕业去向落实率" in html


def test_report_surfaces_demand_profile_and_curriculum_matrix():
    result = _result()
    result["occupation"]["requirements"] = {
        "education_distribution": {"本科": 100, "硕士": 50}, "median_salary": 20000}
    result["market"] = {"industries": [["互联网", 900], ["教育", 100]],
                        "n_target_jobs": 1000, "raw_count": 5000,
                        "deduplicated_count": 2000}
    result["course_skill_matrix"] = {
        "course_ids": ["c1", "c2"], "skills": ["Python", "SQL"],
        "matrix": [[1, 0], [1, 1]], "credits_by_skill": {"Python": 6.0, "SQL": 3.0},
        "unmapped_courses": ["大学英语"]}
    result["courses"] = [{"course_id": "c1", "name": "程序设计", "credits": 3.0,
                          "is_required": True, "source_document": "a/b/培养方案.pdf"}]
    html = render_result(result, "all")
    for marker in ("需求侧画像", "岗位学历结构", "招聘行业分布",
                   "培养方案解剖", "课程 × 技能矩阵", "数据资产总览"):
        assert marker in html, f"缺少维度：{marker}"
