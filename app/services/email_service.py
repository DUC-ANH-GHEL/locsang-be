from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Iterable, Optional

# Local imports (assume these are defined in the project)
from app.core.config import Settings
settings = Settings()

# Placeholder logger using standard logging
logger = logging.getLogger("locsang-be")

# Placeholder implementations for missing utility functions
def _clean_text(val):
    if val is None:
        return ""
    return str(val).strip()

def _parse_recipients(val):
    if not val:
        return []
    if isinstance(val, str):
        return [x.strip() for x in val.split(",") if x.strip()]
    return list(val)

def _resolve_sender_email():
    return getattr(settings, "SMTP_FROM_EMAIL", "noreply@locsang.shop")


def _resolve_admin_contact_recipients() -> list[str]:
    configured = _parse_recipients(settings.CONTACT_NOTIFICATION_TO_EMAIL)
    if configured:
        return configured
    fallback = _resolve_sender_email()
    return [fallback] if fallback else []


def _smtp_login_if_needed(server: smtplib.SMTP) -> None:
    username = _clean_text(settings.SMTP_USERNAME)
    password = str(settings.SMTP_PASSWORD or "")
    if username and password:
        server.login(username, password)


def _send_email_sync(
    *,
    subject: str,
    body_text: str,
    recipients: Iterable[str],
    reply_to: Optional[str] = None,
    body_html: Optional[str] = None,
) -> bool:
    recipient_list = [str(item).strip() for item in recipients if str(item).strip()]
    if not recipient_list:
        return False

    smtp_host = _clean_text(settings.SMTP_HOST)
    smtp_port = int(settings.SMTP_PORT or 587)
    sender_email = _resolve_sender_email()
    if not smtp_host or not sender_email:
        logger.warning(
            "Skip email send because SMTP is not fully configured (host_set=%s, sender_set=%s)",
            bool(smtp_host),
            bool(sender_email),
        )
        return False

    message = EmailMessage()
    message["Subject"] = str(subject or "").strip() or "Lộc Sang"
    message["From"] = formataddr((str(settings.SMTP_FROM_NAME or "Lộc Sang"), sender_email))
    message["To"] = ", ".join(recipient_list)
    clean_reply_to = _clean_text(reply_to)
    if clean_reply_to:
        message["Reply-To"] = clean_reply_to

    if body_html:
        # multipart/alternative: text/plain + text/html
        message.set_content(str(body_text or ""))
        message.add_alternative(str(body_html), subtype="html")
    else:
        message.set_content(str(body_text or ""))

    if bool(settings.SMTP_USE_SSL):
        with smtplib.SMTP_SSL(host=smtp_host, port=smtp_port, timeout=20) as server:
            _smtp_login_if_needed(server)
            server.send_message(message)
        return True

    with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=20) as server:
        server.ehlo()
        if bool(settings.SMTP_USE_TLS):
            server.starttls()
            server.ehlo()
        _smtp_login_if_needed(server)
        server.send_message(message)
    return True


async def send_email(
    *,
    subject: str,
    body_text: str,
    recipients: Iterable[str],
    reply_to: Optional[str] = None,
    body_html: Optional[str] = None,
) -> bool:
    try:
        return await asyncio.to_thread(
            _send_email_sync,
            subject=subject,
            body_text=body_text,
            recipients=recipients,
            reply_to=reply_to,
            body_html=body_html,
        )
    except Exception:
        logger.exception("Failed to send email")
        return False


def _build_contact_admin_body(
    *,
    contact_id: int,
    name: str,
    phone: str,
    email: Optional[str],
    subject: Optional[str],
    message: str,
) -> str:
    subject_text = _clean_text(subject) or "(khong co chu de)"
    email_text = _clean_text(email) or "(khong cung cap)"
    return "\n".join(
        [
            "Co lien he moi tu website Lộc Sang.",
            "",
            f"Ma lien he: #{contact_id}",
            f"Ten: {name}",
            f"So dien thoai: {phone}",
            f"Email: {email_text}",
            f"Chu de: {subject_text}",
            "",
            "Noi dung:",
            message,
        ]
    )


def _build_contact_auto_reply_body(*, name: str, phone: str, message: str, html: bool = False) -> str:
        if html:
                return f"""
<div style='background:#fff9f0;padding:0;margin:0;font-family:Segoe UI,Arial,sans-serif;'>
    <table width='100%' cellpadding='0' cellspacing='0' style='max-width:520px;margin:32px auto 0 auto;background:#fff;border-radius:18px;box-shadow:0 2px 16px #e9e2d4;padding:0 0 32px 0;'>
        <tr>
            <td style='padding:32px 0 0 0;text-align:center;'>
                <img src='https://res.cloudinary.com/diwxfpt92/image/upload/v1770981822/logo_d2wmlf.png' alt='Lộc Sang' style='height:56px;margin-bottom:8px;'>
                <div style='font-size:24px;font-weight:700;color:#8a4f41;margin-bottom:4px;'>Lộc Sang</div>
                <div style='font-size:15px;color:#8a4f41;font-weight:500;margin-bottom:18px;'>Xin chào {name},</div>
            </td>
        </tr>
        <tr>
            <td style='padding:0 32px;'>
                <div style='font-size:16px;color:#2e2a22;margin-bottom:18px;'>
                    Chúng tôi đã nhận được liên hệ của bạn.<br>
                    <span style='color:#fdb19f;'>Lộc Sang sẽ phản hồi sớm nhất có thể!</span>
                </div>
                <div style='background:#f9f3e9;border-radius:12px;padding:16px 20px;margin-bottom:18px;'>
                    <div style='font-size:15px;color:#8a4f41;font-weight:600;margin-bottom:4px;'>Thông tin bạn gửi:</div>
                    <div style='font-size:15px;color:#4f4a41;'><b>Số điện thoại:</b> {phone}</div>
                    <div style='font-size:15px;color:#4f4a41;'><b>Nội dung:</b> {message}</div>
                </div>
                <div style='font-size:15px;color:#8a4f41;margin-bottom:18px;'>Cảm ơn bạn đã tin tưởng Lộc Sang!</div>
                <div style='text-align:center;margin-top:24px;'>
                    <a href='https://locsang.shop/' style='display:inline-block;padding:12px 32px;background:#8a4f41;color:#fff;text-decoration:none;border-radius:24px;font-weight:700;font-size:16px;'>Truy cập Lộc Sang</a>
                </div>
            </td>
        </tr>
        <tr><td style='padding:24px 0 0 0;text-align:center;font-size:12px;color:#b7b1a4;'>© 2024 Lộc Sang</td></tr>
    </table>
</div>
"""
        return "\n".join([
                f"Chao {name},",
                "",
                "Lộc Sang da nhan duoc lien he cua ban.",
                "Chung toi se phan hoi som nhat co the.",
                "",
                f"So dien thoai: {phone}",
                "Noi dung ban gui:",
                message,
                "",
                "Cam on ban da tin tuong Lộc Sang.",
        ])


async def send_contact_email_flow(
    *,
    contact_id: int,
    name: str,
    phone: str,
    message: str,
    email: Optional[str] = None,
    subject: Optional[str] = None,
) -> None:
    admin_recipients = _resolve_admin_contact_recipients()
    admin_subject_suffix = _clean_text(subject)
    admin_subject = f"[Lộc Sang Contact #{contact_id}] {admin_subject_suffix}" if admin_subject_suffix else f"[Lộc Sang Contact #{contact_id}]"

    if admin_recipients:
        admin_sent = await send_email(
            subject=admin_subject,
            body_text=_build_contact_admin_body(
                contact_id=contact_id,
                name=name,
                phone=phone,
                email=email,
                subject=subject,
                message=message,
            ),
            recipients=admin_recipients,
            reply_to=email,
        )
        if not admin_sent:
            logger.warning("Contact admin email not sent for contact_id=%s", contact_id)
    else:
        logger.warning("Contact admin email skipped due to empty recipients for contact_id=%s", contact_id)

    customer_email = _clean_text(email)
    if bool(settings.CONTACT_SEND_AUTO_REPLY) and customer_email:
        customer_sent = await send_email(
            subject="Lộc Sang da nhan duoc lien he cua ban",
            body_text=_build_contact_auto_reply_body(name=name, phone=phone, message=message),
            recipients=[customer_email],
        )
        if not customer_sent:
            logger.warning("Contact auto-reply email not sent for contact_id=%s", contact_id)
    elif bool(settings.CONTACT_SEND_AUTO_REPLY):
        logger.warning("Contact auto-reply skipped due to empty customer email for contact_id=%s", contact_id)


def _build_password_reset_body(*, reset_url: str, expires_minutes: int) -> str:
    return "\n".join(
        [
            "Ban vua yeu cau dat lai mat khau tai Lộc Sang.",
            "",
            "Nhan vao link ben duoi de dat lai mat khau:",
            reset_url,
            "",
            f"Lien ket se het han sau {max(1, int(expires_minutes))} phut.",
            "Neu ban khong yeu cau thao tac nay, hay bo qua email nay.",
        ]
    )


def _build_password_changed_body(*, frontend_base_url: str) -> str:
    return "\n".join(
        [
            "Mat khau tai khoan Lộc Sang cua ban vua duoc thay doi thanh cong.",
            "",
            "Neu day khong phai la ban, vui long doi mat khau ngay lap tuc va lien he ho tro.",
            f"Trang web: {frontend_base_url}",
        ]
    )


async def send_password_reset_email(*, recipient_email: str, reset_url: str, expires_minutes: int) -> bool:
    clean_email = _clean_text(recipient_email)
    clean_url = _clean_text(reset_url)
    if not clean_email or not clean_url:
        return False
    return await send_email(
        subject="Lộc Sang - Dat lai mat khau",
        body_text=_build_password_reset_body(reset_url=clean_url, expires_minutes=expires_minutes),
        body_html=_build_password_reset_body(reset_url=clean_url, expires_minutes=expires_minutes, html=True),
        recipients=[clean_email],
    )


async def send_password_changed_email(*, recipient_email: str) -> bool:
    clean_email = _clean_text(recipient_email)
    if not clean_email:
        return False
    frontend_base_url = str(settings.FRONTEND_BASE_URL or "https://locsang.shop").rstrip("/")
    return await send_email(
        subject="Lộc Sang - Mat khau da duoc thay doi",
        body_text=_build_password_changed_body(frontend_base_url=frontend_base_url),
        body_html=_build_password_changed_body(frontend_base_url=frontend_base_url, html=True),
        recipients=[clean_email],
    )


def _resolve_order_admin_recipients() -> list[str]:
    configured = _parse_recipients(settings.ORDER_NOTIFICATION_TO_EMAIL)
    if configured:
        return configured
    contact_fallback = _parse_recipients(settings.CONTACT_NOTIFICATION_TO_EMAIL)
    if contact_fallback:
        return contact_fallback
    sender_fallback = _resolve_sender_email()
    return [sender_fallback] if sender_fallback else []


def _format_order_items_for_email(items: list[dict[str, object]]) -> str:
    if not items:
        return "- (khong co chi tiet san pham)"

    def _build_password_reset_body(*, reset_url: str, expires_minutes: int, html: bool = False) -> str:
        if html:
            return f"""
    <div style='background:#fff9f0;padding:0;margin:0;font-family:Segoe UI,Arial,sans-serif;'>
      <table width='100%' cellpadding='0' cellspacing='0' style='max-width:520px;margin:32px auto 0 auto;background:#fff;border-radius:18px;box-shadow:0 2px 16px #e9e2d4;padding:0 0 32px 0;'>
        <tr>
          <td style='padding:32px 0 0 0;text-align:center;'>
            <img src='https://res.cloudinary.com/diwxfpt92/image/upload/v1770981822/logo_d2wmlf.png' alt='Lộc Sang' style='height:56px;margin-bottom:8px;'>
            <div style='font-size:24px;font-weight:700;color:#8a4f41;margin-bottom:4px;'>Lộc Sang</div>
          </td>
        </tr>
        <tr>
          <td style='padding:0 32px;'>
            <div style='font-size:16px;color:#2e2a22;margin-bottom:18px;'>
              Bạn vừa yêu cầu đặt lại mật khẩu tại <b>Lộc Sang</b>.<br>
              <span style='color:#fdb19f;'>Nhấn vào nút bên dưới để đặt lại mật khẩu:</span>
            </div>
            <div style='text-align:center;margin:24px 0;'>
              <a href='{reset_url}' style='display:inline-block;padding:12px 32px;background:#8a4f41;color:#fff;text-decoration:none;border-radius:24px;font-weight:700;font-size:16px;'>Đặt lại mật khẩu</a>
            </div>
            <div style='font-size:15px;color:#4f4a41;margin-bottom:12px;'>
              Liên kết sẽ hết hạn sau <b>{max(1, int(expires_minutes))} phút</b>.<br>
              Nếu bạn không yêu cầu thao tác này, hãy bỏ qua email này.
            </div>
          </td>
        </tr>
        <tr><td style='padding:24px 0 0 0;text-align:center;font-size:12px;color:#b7b1a4;'>© 2024 Lộc Sang</td></tr>
      </table>
    </div>
    """
        return "\n".join([
            "Ban vua yeu cau dat lai mat khau tai Lộc Sang.",
            "",
            "Nhan vao link ben duoi de dat lai mat khau:",
            reset_url,
            "",
            f"Lien ket se het han sau {max(1, int(expires_minutes))} phut.",
            "Neu ban khong yeu cau thao tac nay, hay bo qua email nay.",
        ])

def _build_order_admin_body(
    *,
    order_id: int,
    tracking_code: str,
    receiver_name: str,
    receiver_phone: str,
    receiver_address: str,
    receiver_email: Optional[str],
    payment_method: str,
    total_amount: float,
    items: list[dict[str, object]],
    html: bool = False,
) -> str:
    email_text = _clean_text(receiver_email) or "(khong cung cap)"
    return "\n".join(
        [
            "Co don hang moi tu website Lộc Sang.",
            "",
            f"Order ID: #{order_id}",
            f"Tracking code: {tracking_code}",
            f"Nguoi nhan: {receiver_name}",
            f"Dien thoai: {receiver_phone}",
            f"Email: {email_text}",
            f"Dia chi: {receiver_address}",
            f"Thanh toan: {payment_method}",
            f"Tong tien: {float(total_amount or 0):.0f}",
            "",
            "Chi tiet san pham:",
            _format_order_items_for_email(items),
        ]
    )


def _build_order_auto_reply_body(
        *,
        tracking_code: str,
        receiver_name: str,
        receiver_phone: str,
        receiver_address: str,
        payment_method: str,
        total_amount: float,
        items: list[dict[str, object]],
        html: bool = False,
) -> str:
        if html:
                items_html = "".join([
                        f"<tr><td style='padding:6px 0;font-size:15px;color:#4f4a41;'>{idx+1}. {item.get('name','Sản phẩm')} <span style='color:#b7b1a4;'>x{item.get('quantity',1)}</span> <span style='float:right;color:#8a4f41;font-weight:600;'>{float(item.get('subtotal',0)) or float(item.get('unit_price',0)) or 0:,.0f}đ</span></td></tr>"
                        for idx, item in enumerate(items or [])
                ])
                return f"""
<div style='background:#fff9f0;padding:0;margin:0;font-family:Segoe UI,Arial,sans-serif;'>
    <table width='100%' cellpadding='0' cellspacing='0' style='max-width:520px;margin:32px auto 0 auto;background:#fff;border-radius:18px;box-shadow:0 2px 16px #e9e2d4;padding:0 0 32px 0;'>
        <tr>
            <td style='padding:32px 0 0 0;text-align:center;'>
                <img src='https://res.cloudinary.com/diwxfpt92/image/upload/v1770981822/logo_d2wmlf.png' alt='Lộc Sang' style='height:56px;margin-bottom:8px;'>
                <div style='font-size:24px;font-weight:700;color:#8a4f41;margin-bottom:4px;'>Lộc Sang</div>
                <div style='font-size:15px;color:#8a4f41;font-weight:500;margin-bottom:18px;'>Xin chào {receiver_name},</div>
            </td>
        </tr>
        <tr>
            <td style='padding:0 32px;'>
                <div style='font-size:16px;color:#2e2a22;margin-bottom:18px;'>
                    Đơn hàng của bạn đã được ghi nhận.<br>
                    <span style='color:#fdb19f;'>Lộc Sang sẽ liên hệ xác nhận và giao hàng sớm nhất!</span>
                </div>
                <div style='background:#f9f3e9;border-radius:12px;padding:16px 20px;margin-bottom:18px;'>
                    <div style='font-size:15px;color:#8a4f41;font-weight:600;margin-bottom:4px;'>Thông tin đơn hàng:</div>
                    <div style='font-size:15px;color:#4f4a41;'><b>Mã đơn:</b> {tracking_code}</div>
                    <div style='font-size:15px;color:#4f4a41;'><b>Số điện thoại:</b> {receiver_phone}</div>
                    <div style='font-size:15px;color:#4f4a41;'><b>Địa chỉ:</b> {receiver_address}</div>
                    <div style='font-size:15px;color:#4f4a41;'><b>Thanh toán:</b> {payment_method}</div>
                    <div style='font-size:15px;color:#4f4a41;'><b>Tạm tính:</b> {float(total_amount or 0):,.0f}đ</div>
                </div>
                <div style='font-size:15px;color:#8a4f41;font-weight:600;margin-bottom:4px;'>Chi tiết sản phẩm:</div>
                <table width='100%' cellpadding='0' cellspacing='0' style='margin-bottom:18px;'>{items_html}</table>
                <div style='font-size:15px;color:#8a4f41;margin-bottom:18px;'>Cảm ơn bạn đã mua sắm tại Lộc Sang!</div>
                <div style='text-align:center;margin-top:24px;'>
                    <a href='https://locsang.shop/' style='display:inline-block;padding:12px 32px;background:#8a4f41;color:#fff;text-decoration:none;border-radius:24px;font-weight:700;font-size:16px;'>Truy cập Lộc Sang</a>
                </div>
            </td>
        </tr>
        <tr><td style='padding:24px 0 0 0;text-align:center;font-size:12px;color:#b7b1a4;'>© 2024 Lộc Sang</td></tr>
    </table>
</div>
"""
        return "\n".join([
                f"Chao {receiver_name},",
                "",
                "Lộc Sang da nhan duoc don hang cua ban.",
                f"Ma theo doi don: {tracking_code}",
                f"So dien thoai nguoi nhan: {receiver_phone}",
                f"Dia chi nhan hang: {receiver_address}",
                f"Phuong thuc thanh toan: {payment_method}",
                f"Tong tien tam tinh: {float(total_amount or 0):.0f}",
                "",
                "Chi tiet san pham:",
                _format_order_items_for_email(items),
                "",
                "Cam on ban da mua sam tai Lộc Sang.",
        ])


async def send_order_email_flow(
    *,
    order_id: int,
    tracking_code: str,
    receiver_name: str,
    receiver_phone: str,
    receiver_address: str,
    payment_method: str,
    total_amount: float,
    items: list[dict[str, object]],
    receiver_email: Optional[str] = None,
) -> None:
    admin_recipients = _resolve_order_admin_recipients()
    if admin_recipients:
            await send_email(
                subject=f"[Lộc Sang Order] {tracking_code}",
                body_text=_build_order_admin_body(
                    order_id=order_id,
                    tracking_code=tracking_code,
                    receiver_name=receiver_name,
                    receiver_phone=receiver_phone,
                    receiver_address=receiver_address,
                    receiver_email=receiver_email,
                    payment_method=payment_method,
                    total_amount=total_amount,
                    items=items,
                ),
                body_html=_build_order_admin_body(
                    order_id=order_id,
                    tracking_code=tracking_code,
                    receiver_name=receiver_name,
                    receiver_phone=receiver_phone,
                    receiver_address=receiver_address,
                    receiver_email=receiver_email,
                    payment_method=payment_method,
                    total_amount=total_amount,
                    items=items,
                    html=True,
                ),
                recipients=admin_recipients,
                reply_to=receiver_email,
            )

    customer_email = _clean_text(receiver_email)
    if bool(settings.ORDER_SEND_AUTO_REPLY) and customer_email:
        await send_email(
            subject=f"Lộc Sang - Xac nhan don hang {tracking_code}",
            body_text=_build_order_auto_reply_body(
                tracking_code=tracking_code,
                receiver_name=receiver_name,
                receiver_phone=receiver_phone,
                receiver_address=receiver_address,
                payment_method=payment_method,
                total_amount=total_amount,
                items=items,
            ),
            recipients=[customer_email],
        )
