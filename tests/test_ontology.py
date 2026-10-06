"""Evaluation dimension 2: skill standardisation."""

from __future__ import annotations

from edumatch.ontology import load_ontology


def test_alias_variants_map_to_one_entity():
    onto = load_ontology()
    ids = {
        onto.by_name("PyTorch").skill_id,
        onto.by_name("torch").skill_id,
        onto.by_name("pytorch框架").skill_id,
        onto.by_name("PyTorch framework").skill_id,
    }
    assert len(ids) == 1


def test_hierarchy_propagation():
    onto = load_ontology()
    names = {onto.get(m.skill_id).name for m in onto.extract("熟悉 RAG 与模型微调")}
    assert {"RAG", "大模型", "人工智能"} <= names


def test_single_letter_alias_needs_boundary():
    onto = load_ontology()
    assert onto.by_name("C语言") is not None
    # "CNN" must not be treated as the C programming language
    mentions = {onto.get(m.skill_id).name for m in onto.extract("掌握 CNN 卷积网络")}
    assert "C语言" not in mentions
    assert "卷积神经网络" in mentions


def test_course_rule_mapping():
    onto = load_ontology()
    skills = {onto.get(sid).name for sid in onto.match_course("深度学习", "PyTorch 框架与 Transformer")}
    # 机器学习与深度学习在本体中是兄弟节点，不存在上下位关系
    assert {"深度学习", "PyTorch", "人工智能"} <= skills
    assert "机器学习" not in skills
