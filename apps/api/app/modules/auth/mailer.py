"""密码重置邮件发送契约与标准 SMTP 适配器。"""

import smtplib
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import urlencode

from anyio import to_thread
from pydantic import SecretStr


class PasswordResetMailer(Protocol):
    """限定认证路由可使用的密码重置投递能力。"""

    async def send_password_reset(self, *, email: str, token: str) -> None:
        """向规范化邮箱发送一次性重置链接。"""
        ...


class SmtpPasswordResetMailer:
    """通过标准 SMTP 协议投递不含用户数据的重置邮件。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        public_web_url: str,
        username: str | None = None,
        password: SecretStr | None = None,
        starttls: bool = True,
    ) -> None:
        """保存启动期已校验的 SMTP 与公开站点配置。"""
        self._host = host
        self._port = port
        self._sender = sender
        self._public_web_url = public_web_url.rstrip("/")
        self._username = username
        self._password = password
        self._starttls = starttls

    async def send_password_reset(self, *, email: str, token: str) -> None:
        """在线程中执行阻塞 SMTP，避免阻塞 API 事件循环。"""
        await to_thread.run_sync(self._send, email, token)

    def _send(self, email: str, token: str) -> None:
        """构造纯文本邮件并在短连接中完成投递。"""
        query = urlencode({"token": token})
        message = EmailMessage()
        message["Subject"] = "重置持仓簿密码"
        message["From"] = self._sender
        message["To"] = email
        message.set_content(
            "请在 30 分钟内打开以下链接设置新密码：\n"
            f"{self._public_web_url}/reset-password?{query}\n\n"
            "如果不是你发起的请求，可以忽略此邮件。"
        )
        with smtplib.SMTP(self._host, self._port, timeout=10) as client:
            if self._starttls:
                client.starttls()
            if self._username is not None and self._password is not None:
                client.login(self._username, self._password.get_secret_value())
            client.send_message(message)
