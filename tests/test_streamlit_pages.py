from streamlit.testing.v1 import AppTest
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "dashboard.py"


def test_all_menu_pages_render_without_exception():
    initial = AppTest.from_file(APP, default_timeout=30).run()
    menu_count = sum(1 for button in initial.button if button.key and str(button.key).startswith("nav-"))
    assert menu_count >= 20
    for index in range(menu_count):
        app = AppTest.from_file(APP, default_timeout=30).run()
        label = app.button[index].label
        result = app.button[index].click().run()
        assert not result.exception, f"页面异常: {label}"
        assert result.title, f"页面没有语义标题: {label}"


def test_watchlist_prefill_survives_holding_form_rerun():
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["page"] = "持仓"
    app.session_state["pending_holding_symbol"] = "AAPL"
    app.session_state["pending_holding_name"] = "Apple"
    app.session_state["pending_holding_type"] = "global_stock"
    first = app.run()
    symbol = next(item for item in first.text_input if item.label == "市场代码")
    assert symbol.value == "AAPL"
    second = app.run()
    symbol = next(item for item in second.text_input if item.label == "市场代码")
    assert symbol.value == "AAPL"
