import pandas as pd

from stock_picker.provider import AkshareProvider


def test_tencent_spot_uses_zxj_as_latest_price():
    class FakeAk:
        @staticmethod
        def stock_zh_a_spot_tx():
            return pd.DataFrame(
                [{
                    "code": "sh600000", "name": "测试", "zxj": "12.34",
                    "turnover": "100", "zsz": "200", "pe_ttm": "10", "zdf": "1.2",
                }]
            )

    provider = AkshareProvider(retries=1)
    frame = provider._spot_tencent(FakeAk)
    assert frame.iloc[0].last_price == 12.34
    assert provider.last_source == "tencent"
