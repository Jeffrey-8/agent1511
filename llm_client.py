# llm_client.py
import logging
import re
import requests
from gigachat import GigaChat

AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"
RQ_UID = "884a110b-feca-430f-bb5e-57d3d06b2ee7"
AUTHORIZATION = (
    "Basic ZDZmMDBiY2EtNTViYi00NTg0LWJkNDAtZjdlNGUzMTY3YjczOmQ2YTUzMmZhLTdmNjMt"
    "NDI4NS1hN2NlLTAzZmZiMWU4YmNjYg=="
)

# обычный логгер модуля (если понадобится для ошибок и т.п.)
logger = logging.getLogger(__name__)

# 🔹 отдельный логгер только для рассуждений и сырого LLM
agent_reason_logger = logging.getLogger("agent_reasoning")
agent_reason_logger.setLevel(logging.INFO)
agent_reason_logger.propagate = False  # НЕ пускать наверх (в консоль)

# хэндлер в файл logs/agent.log
fh = logging.FileHandler("logs/agent.log", encoding="utf-8")
fh.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s - %(message)s")
fh.setFormatter(fmt)
agent_reason_logger.addHandler(fh)


def get_giga_access_token() -> str:
    payload = {"scope": GIGACHAT_SCOPE}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": RQ_UID,
        "Authorization": AUTHORIZATION,
    }
    response = requests.post(AUTH_URL, headers=headers, data=payload, verify=False)
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Не удалось получить access_token: {data}")
    return token


class GigaChatLLM:
    def __init__(self, *_args, **_kwargs):
        token = get_giga_access_token()
        self.llm = GigaChat(
            access_token=token,
            scope=GIGACHAT_SCOPE,
            verify_ssl_certs=False,
        )

    def chat(self, prompt: str) -> str:
        resp = self.llm.chat(prompt)
        content = resp.choices[0].message.content or ""

        # логируем полный сырой ответ в файл reasoning-логов
        agent_reason_logger.info(
            "\n=== RAW ANSWER BEGIN ===\n"
            + content
            + "\n=== RAW ANSWER END ===\n"
        )

        # пробуем вытащить ANSWER
        answer = self._extract_tag(content, "ANSWER")

        # 🔴 ВАЖНО: если ответа внутри <ANSWER> нет или он пустой —
        #          возвращаем весь контент, а не пустую строку
        if not answer.strip():
            logger.warning("[LLM] ANSWER tag not found or empty, returning full content")
            return content.strip()

        return answer.strip()

    @staticmethod
    def _extract_tag(text: str, tag: str) -> str:
        pattern = rf"<{tag}>(.*?)</{tag}>"
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # если тег не найден — вернём ПУСТУЮ строку, а не весь текст,
        # но chat() сверху это обработает и отдаст fallback = content
        return ""
