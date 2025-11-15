# # gigachat_client.py
# import logging
# from typing import List, Dict
#
# from gigachat import GigaChat  # как у тебя
# import requests
# import re
# import json
#
# logger = logging.getLogger(__name__)
#
# AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# GIGACHAT_SCOPE = "GIGACHAT_API_PERS"
# RQ_UID = "884a110b-feca-430f-bb5e-57d3d06b2ee9"
# AUTHORIZATION = "Basic ZDZmMDBiY2EtNTViYi00NTg0LWJkNDAtZjdlNGUzMTY3YjczOmQ2YTUzMmZhLTdmNjMtNDI4NS1hN2NlLTAzZmZiMWU4YmNjYg=="  # твой токен
#
#
# def get_giga_access_token():
#     payload = {"scope": GIGACHAT_SCOPE}
#     headers = {
#         "Content-Type": "application/x-www-form-urlencoded",
#         "Accept": "application/json",
#         "RqUID": RQ_UID,
#         "Authorization": AUTHORIZATION,
#     }
#     response = requests.post(AUTH_URL, headers=headers, data=payload, verify=False)
#     return response.json().get("access_token")
#
#
# class GigaClient:
#     def __init__(self):
#         token = get_giga_access_token()
#         self.llm = GigaChat(
#             access_token=token,
#             scope=GIGACHAT_SCOPE,
#             verify_ssl_certs=False,
#         )
#
#     def chat(self, prompt: str) -> str:
#         """
#         Ожидаем от модели формат:
#         <REASONING>...</REASONING>
#         <ANSWER>...</ANSWER>
#         В логи уходит всё, пользователю вернём только ANSWER.
#         """
#         logger.info(f"[LLM][prompt] {prompt}")
#         resp = self.llm.chat(prompt)
#         content = resp.choices[0].message.content
#         logger.info(f"[LLM][raw_response] {content}")
#
#         # В логах reasoning нам остаётся, можно потом смотреть.
#         answer = self._extract_tag(content, "ANSWER")
#         return answer.strip()
#
#     @staticmethod
#     def _extract_tag(text: str, tag: str) -> str:
#         pattern = rf"<{tag}>(.*?)</{tag}>"
#         m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
#         if m:
#             return m.group(1).strip()
#         # если нет тега — возвращаем весь текст
#         return text.strip()
