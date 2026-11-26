"""Local rejection of explicit attempts to redirect the trainer."""
import re
import unicodedata

SCOPE_REFUSAL = "Давай вернёмся к тренировке. Можно попросить подсказку, пример или спросить о смежной теме."

_DIRECT_REDIRECT = re.compile(
    r"^(?:пожалуйста[ ,]+)?(?:"
    r"(?:игнорируй|забудь)\s+(?:(?:все|твои|предыдущие)\s+)*(?:инструкции|правила)\b"
    r"|(?:напиши|создай|сделай|сверстай)\s+(?:(?:мне|нам)\s+)?сайт\s+про\s+детей\b"
    r"|я\s+(?:ребенок|несовершеннолетн\w*)\b.{0,100}\b(?:в плену|попал[аи]? в плен|меня похитили)\b"
    r"|ignore\s+(?:(?:all|your|previous)\s+)*(?:instructions|rules)\b"
    r")",
    re.IGNORECASE,
)


def obvious_redirect(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return bool(_DIRECT_REDIRECT.match(" ".join(normalized.split())))
