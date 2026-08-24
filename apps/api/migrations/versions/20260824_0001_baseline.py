"""建立 V2 空库迁移基线。"""

from collections.abc import Sequence

revision: str = "20260824_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """登记空库基线；业务表由后续模块迁移增量创建。"""


def downgrade() -> None:
    """空库基线不包含需要撤销的数据库对象。"""
