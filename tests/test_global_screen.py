import pandas as pd

from stock_picker.global_screen import score_global_features


def test_global_score_drops_incomplete_and_ranks_quality():
    frame = pd.DataFrame([
        {"symbol":"GOOD", "pe":15, "roa_proxy":.15, "fcf_margin_proxy":.20, "return_1y":.25, "max_drawdown":-.12},
        {"symbol":"WEAK", "pe":35, "roa_proxy":.03, "fcf_margin_proxy":.04, "return_1y":-.05, "max_drawdown":-.40},
        {"symbol":"MISS", "pe":10, "roa_proxy":None, "fcf_margin_proxy":.20, "return_1y":.2, "max_drawdown":-.1},
    ])
    ranked = score_global_features(frame)
    assert ranked.symbol.tolist() == ["GOOD", "WEAK"]
    assert ranked.iloc[0].score > ranked.iloc[1].score
