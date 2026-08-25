"""按环境配置创建可替换的行情 Provider。"""

from dataclasses import dataclass

from app.core.config import Settings
from app.modules.market_data.providers.fund import FundProvider
from app.modules.market_data.providers.http import ProviderHttpClient
from app.modules.market_data.providers.stock import StockProvider


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """集中持有共享 HTTP 连接池和模块 Provider。"""

    http: ProviderHttpClient
    stock: StockProvider
    fund: FundProvider

    async def close(self) -> None:
        """释放 Provider 共享的 HTTP 连接池。"""
        await self.http.close()


def create_provider_bundle(settings: Settings) -> ProviderBundle:
    """从启动期配置创建股票与基金 Provider。"""
    http = ProviderHttpClient()
    return ProviderBundle(
        http=http,
        stock=StockProvider(http),
        fund=FundProvider(http, estimate_enabled=settings.fund_estimate_enabled),
    )
