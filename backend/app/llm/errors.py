"""Safe P2 failures; no provider or document content in public messages."""

MESSAGES = {
    "not_configured": "تنظیمات سرویس هوش مصنوعی کامل نیست.",
    "timeout": "زمان پاسخ سرویس تمام شد؛ دوباره تلاش کنید.",
    "api": "سرویس هوش مصنوعی موقتاً در دسترس نیست.",
    "bad_json": "پاسخ سرویس قابل پردازش نبود؛ دوباره تلاش کنید.",
    "invalid": "اطلاعات ورودی قابل پردازش نیست.",
    "conflict": "اصلاح مبهم است یا با اطلاعات قبلی سازگار نیست؛ مهارت را دقیق‌تر بیان کنید.",
    "document": "فایل خالی، رمزدار یا ناخواناست؛ برای فایل اسکن‌شده ابتدا OCR لازم است.",
}


class P2Error(ValueError):
    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(MESSAGES.get(kind, MESSAGES["invalid"]))

    @property
    def status_code(self) -> int:
        return {"not_configured": 503, "api": 502, "timeout": 504, "bad_json": 502}.get(self.kind, 422)
