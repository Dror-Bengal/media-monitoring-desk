"""Telegram Bot API and WhatsApp Green-API. A receipt belongs to one destination."""
from dataclasses import dataclass
from urllib.parse import quote

import requests

@dataclass
class Destination:
    name: str
    url: str
    chat: str

    def send(self, message):
        if self.name == "telegram":
            payload = {"chat_id":self.chat, "text":message, "disable_web_page_preview":True}
        else:
            payload = {"chatId":self.chat, "message":message}
        try:
            response = requests.post(self.url, json=payload, timeout=15, allow_redirects=False)
            data = response.json()
            if self.name == "telegram":
                ref = data.get("result", {}).get("message_id") if data.get("ok") is True else None
            else:
                ref = data.get("idMessage")
            if response.status_code == 200 and ref:
                return str(ref)
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass
        # Provider URLs contain credentials; keep them out of errors and logs.
        raise RuntimeError(self.name + " did not confirm the message")

def destinations(env, telegram_base="https://api.telegram.org"):
    result = []
    if env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_CHAT_ID"):
        if not all(env.get(k) for k in ("TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID")):
            raise ValueError("Telegram requires both a bot token and a chat ID")
        token = quote(env["TELEGRAM_BOT_TOKEN"], safe=":")
        result.append(Destination("telegram", f"{telegram_base}/bot{token}/sendMessage", env["TELEGRAM_CHAT_ID"]))
    if any(env.get(k) for k in ("GREEN_API_INSTANCE_ID", "GREEN_API_TOKEN", "WHATSAPP_GROUP_ID")):
        if not all(env.get(k) for k in ("GREEN_API_URL","GREEN_API_INSTANCE_ID","GREEN_API_TOKEN","WHATSAPP_GROUP_ID")):
            raise ValueError("WhatsApp requires a complete Green-API destination")
        host = env["GREEN_API_URL"].rstrip("/")
        instance, token = (quote(env[key], safe="") for key in ("GREEN_API_INSTANCE_ID","GREEN_API_TOKEN"))
        result.append(Destination("whatsapp", f"{host}/waInstance{instance}/sendMessage/{token}", env["WHATSAPP_GROUP_ID"]))
    if not result or any(not item.chat for item in result):
        raise ValueError("Configure a complete Telegram or WhatsApp destination")
    return result
