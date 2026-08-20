from pathlib import Path


def test_every_declared_page_has_a_render_branch():
    source = Path("dashboard.py").read_text(encoding="utf-8")
    # Extract literal entries from the intentionally explicit page registry.
    section = source.split("PAGES = {", 1)[1].split("}\n", 1)[0]
    import re
    groups = {"核心流程", "工作台", "市场雷达", "我的组合", "股票", "基金与ETF", "债券", "商品", "事件提醒", "系统"}
    labels = [value for value in re.findall(r'"([^\"]+)"', section) if value not in groups]
    assert labels
    for label in labels:
        assert f'page == "{label}"' in source, f"菜单没有渲染分支: {label}"


def test_removed_page_name_is_not_a_navigation_target():
    source = Path("dashboard.py").read_text(encoding="utf-8")
    assert 'st.session_state["page"] = "股票概览"' not in source
