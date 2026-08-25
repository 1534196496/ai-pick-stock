"""跨模块复用的 API 边界模型。"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """统一公开字段使用 camelCase，并允许服务端按 Python 名构造。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
