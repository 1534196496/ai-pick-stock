"""把不同录入方式规范化为同一种持仓投影。"""

from decimal import Decimal

from app.modules.portfolios.domain import PositionDraft
from app.modules.portfolios.enums import CostInputMode
from app.modules.portfolios.money import (
    MAX_AMOUNT,
    MAX_QUANTITY,
    DecimalRuleError,
    calculate_decimal,
    require_positive_input,
    require_signed_input,
)
from app.modules.portfolios.position_commands import (
    FundAmountPositionCommand,
    FundSharesPositionCommand,
    StockPositionCommand,
)


class PositionNormalizationError(ValueError):
    """表示持仓输入组合或十进制值不满足领域规则。"""

    def __init__(self, *, code: str, message: str) -> None:
        """保存稳定领域错误码和可直接修正的中文提示。"""
        super().__init__(message)
        self.code = code
        self.message = message


class StockPositionNormalizer:
    """把股票数量和一种成本输入转换为统一持仓投影。"""

    def normalize(self, command: StockPositionCommand) -> PositionDraft:
        """校验输入精度，并计算缺失的总成本或平均成本。"""
        try:
            quantity = require_positive_input(
                command.quantity,
                maximum=MAX_QUANTITY,
                field="持有数量",
            )
            total_cost, average_cost = self._normalize_cost(command, quantity=quantity)
        except DecimalRuleError as error:
            raise PositionNormalizationError(
                code="INVALID_POSITION_DECIMAL",
                message=str(error),
            ) from error
        return PositionDraft(
            group_id=command.group_id,
            instrument_id=command.instrument_id,
            trade_date=command.input_date,
            quantity=quantity,
            total_cost=total_cost,
            average_cost=average_cost,
        )

    def _normalize_cost(
        self,
        command: StockPositionCommand,
        *,
        quantity: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """要求成本二选一，并计算另一种规范化成本。"""
        if command.cost_input_mode == CostInputMode.TOTAL_COST:
            if command.total_cost is None or command.average_cost is not None:
                raise PositionNormalizationError(
                    code="INVALID_COST_INPUT",
                    message="选择总成本时只能填写总成本",
                )
            total_cost = require_positive_input(
                command.total_cost,
                maximum=MAX_AMOUNT,
                field="总成本",
            )
            average_cost = calculate_decimal(
                total_cost / quantity,
                maximum=MAX_AMOUNT,
                field="平均成本",
            )
            return total_cost, average_cost

        if command.cost_input_mode == CostInputMode.AVERAGE_COST:
            if command.average_cost is None or command.total_cost is not None:
                raise PositionNormalizationError(
                    code="INVALID_COST_INPUT",
                    message="选择平均成本时只能填写平均成本",
                )
            average_cost = require_positive_input(
                command.average_cost,
                maximum=MAX_AMOUNT,
                field="平均成本",
            )
            total_cost = calculate_decimal(
                quantity * average_cost,
                maximum=MAX_AMOUNT,
                field="总成本",
            )
            return total_cost, average_cost

        raise PositionNormalizationError(
            code="INVALID_COST_INPUT_MODE",
            message="不支持的成本输入方式",
        )


class FundAmountPositionNormalizer:
    """使用添加时的可用净值把基金金额转换为份额和成本。"""

    def normalize(self, command: FundAmountPositionCommand) -> PositionDraft:
        """实时计算基金份额；没有任何可用净值时拒绝保存半成品持仓。"""
        if command.nav_basis is None:
            raise PositionNormalizationError(
                code="FUND_NAV_UNAVAILABLE",
                message="暂时无法取得基金净值，请稍后重试或改用份额录入",
            )
        try:
            current_value = require_positive_input(
                command.current_value,
                maximum=MAX_AMOUNT,
                field="当前持有金额",
            )
            holding_profit = require_signed_input(
                command.holding_profit,
                maximum=MAX_AMOUNT,
                field="持有收益",
            )
            total_cost = calculate_decimal(
                current_value - holding_profit,
                maximum=MAX_AMOUNT,
                field="总成本",
            )
            nav = require_positive_input(
                command.nav_basis.value,
                maximum=MAX_AMOUNT,
                field="基金单位净值",
            )
            quantity = calculate_decimal(
                current_value / nav,
                maximum=MAX_QUANTITY,
                field="推算份额",
            )
            average_cost = calculate_decimal(
                total_cost / quantity,
                maximum=MAX_AMOUNT,
                field="平均成本",
            )
        except DecimalRuleError as error:
            raise PositionNormalizationError(
                code="INVALID_POSITION_DECIMAL",
                message=str(error),
            ) from error
        return PositionDraft(
            group_id=command.group_id,
            instrument_id=command.instrument_id,
            trade_date=command.input_date,
            quantity=quantity,
            total_cost=total_cost,
            average_cost=average_cost,
        )


class FundSharesPositionNormalizer:
    """把基金份额和一种成本输入转换为统一持仓投影。"""

    def normalize(self, command: FundSharesPositionCommand) -> PositionDraft:
        """复用份额与成本规则，保留基金自身的资产类型校验边界。"""
        return StockPositionNormalizer().normalize(
            StockPositionCommand(
                group_id=command.group_id,
                instrument_id=command.instrument_id,
                input_date=command.input_date,
                quantity=command.quantity,
                cost_input_mode=command.cost_input_mode,
                total_cost=command.total_cost,
                average_cost=command.average_cost,
            )
        )
