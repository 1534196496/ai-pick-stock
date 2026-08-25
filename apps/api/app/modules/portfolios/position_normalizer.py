"""股票持仓输入规范化规则。"""

from datetime import date
from decimal import Decimal

from app.modules.portfolios.domain import PositionDraft
from app.modules.portfolios.enums import CostInputMode, PositionInputMode
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
    """把股票数量和一种成本输入转换为统一规范化持仓。"""

    def normalize(self, command: StockPositionCommand) -> PositionDraft:
        """校验输入形状和精度，并计算缺失的总成本或平均成本。"""
        try:
            quantity = require_positive_input(
                command.quantity,
                maximum=MAX_QUANTITY,
                field="持有数量",
            )
            input_total_cost, input_average_cost, total_cost, average_cost = (
                self._normalize_cost(command, quantity=quantity)
            )
        except DecimalRuleError as error:
            raise PositionNormalizationError(
                code="INVALID_POSITION_DECIMAL",
                message=str(error),
            ) from error

        return PositionDraft(
            account_id=command.account_id,
            instrument_id=command.instrument_id,
            input_mode=PositionInputMode.STOCK_SHARES,
            cost_input_mode=command.cost_input_mode,
            input_date=command.input_date,
            input_quantity=quantity,
            input_total_cost=input_total_cost,
            input_average_cost=input_average_cost,
            input_current_value=None,
            input_holding_profit=None,
            quantity=quantity,
            total_cost=total_cost,
            average_cost=average_cost,
        )

    def _normalize_cost(
        self,
        command: StockPositionCommand,
        *,
        quantity: Decimal,
    ) -> tuple[Decimal | None, Decimal | None, Decimal, Decimal]:
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
            return total_cost, None, total_cost, average_cost

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
            return None, average_cost, total_cost, average_cost

        raise PositionNormalizationError(
            code="INVALID_COST_INPUT_MODE",
            message="不支持的成本输入方式",
        )


class FundAmountPositionNormalizer:
    """把基金当前金额与持有收益转换为成本和可选推算份额。"""

    def normalize(self, command: FundAmountPositionCommand) -> PositionDraft:
        """使用实际日期官方单位净值推算份额，缺净值时保留金额快照。"""
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
            quantity, average_cost, basis_nav, basis_date = self._estimate_quantity(
                command,
                current_value=current_value,
                total_cost=total_cost,
            )
        except DecimalRuleError as error:
            raise PositionNormalizationError(
                code="INVALID_POSITION_DECIMAL",
                message=str(error),
            ) from error

        return PositionDraft(
            account_id=command.account_id,
            instrument_id=command.instrument_id,
            input_mode=PositionInputMode.FUND_AMOUNT,
            cost_input_mode=None,
            input_date=command.input_date,
            input_quantity=None,
            input_total_cost=None,
            input_average_cost=None,
            input_current_value=current_value,
            input_holding_profit=holding_profit,
            quantity=quantity,
            total_cost=total_cost,
            average_cost=average_cost,
            quantity_estimated=quantity is not None,
            quantity_basis_nav=basis_nav,
            quantity_basis_nav_date=basis_date,
        )

    @staticmethod
    def _estimate_quantity(
        command: FundAmountPositionCommand,
        *,
        current_value: Decimal,
        total_cost: Decimal,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, date | None]:
        """有官方净值时推算份额和平均成本，否则保持待补份额。"""
        basis = command.nav_basis
        if basis is None:
            return None, None, None, None
        nav = require_positive_input(
            basis.value,
            maximum=MAX_AMOUNT,
            field="官方单位净值",
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
        return quantity, average_cost, nav, basis.nav_date


class FundSharesPositionNormalizer:
    """把基金份额和一种成本输入转换为精确模式持仓。"""

    def normalize(self, command: FundSharesPositionCommand) -> PositionDraft:
        """复用股票成本规则，但保持基金份额录入模式和审计字段。"""
        stock_draft = StockPositionNormalizer().normalize(
            StockPositionCommand(
                account_id=command.account_id,
                instrument_id=command.instrument_id,
                input_date=command.input_date,
                quantity=command.quantity,
                cost_input_mode=command.cost_input_mode,
                total_cost=command.total_cost,
                average_cost=command.average_cost,
            )
        )
        return PositionDraft(
            account_id=stock_draft.account_id,
            instrument_id=stock_draft.instrument_id,
            input_mode=PositionInputMode.FUND_SHARES,
            cost_input_mode=stock_draft.cost_input_mode,
            input_date=stock_draft.input_date,
            input_quantity=stock_draft.input_quantity,
            input_total_cost=stock_draft.input_total_cost,
            input_average_cost=stock_draft.input_average_cost,
            input_current_value=None,
            input_holding_profit=None,
            quantity=stock_draft.quantity,
            total_cost=stock_draft.total_cost,
            average_cost=stock_draft.average_cost,
        )
