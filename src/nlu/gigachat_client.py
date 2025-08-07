# --- НАЧАЛО ОБНОВЛЕННОГО ФАЙЛА ---

from langchain_gigachat import GigaChat
from langchain_core.messages import SystemMessage, HumanMessage
from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
import logging
from typing import Optional, Dict, Any, List
import asyncio
import json

from src.config import settings

logger = logging.getLogger(__name__)


class TokenUsageLogger(BaseCallbackHandler):
    """Callback-класс для логирования использования токенов."""

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> Any:
        logger.info("... GigaChat LLM call starting ...")

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        token_usage = response.llm_output.get("token_usage", {})
        if token_usage:
            prompt_tokens = token_usage.get("prompt_tokens", "N/A")
            completion_tokens = token_usage.get("completion_tokens", "N/A")
            total_tokens = token_usage.get("total_tokens", "N/A")
            logger.info(
                f"GigaChat LLM call finished. "
                f"Tokens Used: [Prompt: {prompt_tokens}, Completion: {completion_tokens}, Total: {total_tokens}]"
            )
        else:
            logger.warning(
                "GigaChat LLM call finished, but token usage info is not available."
            )


class GigaChatService:
    _clients: Dict[str, GigaChat] = {}

    def _get_client(self, purpose: str) -> GigaChat:
        if purpose not in self._clients:
            logger.info(f"Создание нового клиента GigaChat для цели: '{purpose}'")
            temp_map = {
                "extract": settings.GIGACHAT_TEMPERATURE_SUMMARIZE,
                "nlu": settings.GIGACHAT_TEMPERATURE_NLU,
            }
            tokens_map = {
                "extract": settings.GIGACHAT_MAX_TOKENS_SUMMARIZE,
                "nlu": settings.GIGACHAT_MAX_TOKENS_NLU,
            }

            try:
                self._clients[purpose] = GigaChat(
                    credentials=settings.GIGACHAT_CREDENTIALS,
                    scope=settings.GIGACHAT_SCOPE,
                    model=settings.GIGACHAT_MODEL,
                    temperature=temp_map.get(purpose, 0.01),
                    max_tokens=tokens_map.get(purpose, 4096),
                    verify_ssl_certs=settings.GIGACHAT_VERIFY_SSL_CERTS,
                    timeout=settings.GIGACHAT_TIMEOUT,
                    profanity_check=settings.GIGACHAT_PROFANITY_CHECK,
                )
            except Exception as e:
                logger.critical(
                    f"Не удалось создать клиент GigaChat: {e}", exc_info=True
                )
                raise
        return self._clients[purpose]

    # --- ИЗМЕНЕНИЕ: Добавлено более строгое правило для дат в промпт ---
    async def extract_and_categorize_events(
        self, chunks: List[str], search_params: Dict[str, Any]
    ) -> Dict[str, List]:

        empty_result = {
            "perfect_matches": [],
            "near_date_matches": [],
            "other_mismatches": [],
        }

        if not chunks:
            return empty_result

        client = self._get_client("extract")
        criteria_json = json.dumps(search_params, ensure_ascii=False, indent=2)
        system_prompt = (
            "Ты — ведущий аналитик по бизнес-мероприятиям. Твоя задача — выполнить полный цикл анализа предоставленных текстов по заданным критериям и вернуть готовый результат в виде ОДНОГО JSON-объекта.\n\n"
            "**ТВОЙ АЛГОРИТМ ДЕЙСТВИЙ:**\n"
            "1.  **ИЗВЛЕЧЕНИЕ:** Внимательно прочитай ВСЕ предоставленные фрагменты текста. Найди в них упоминания АБСОЛЮТНО ВСЕХ бизнес-мероприятий. Для каждого извлеки: `name`, `dates`, `location`, `description`.\n"
            "2.  **АНАЛИЗ И КАТЕГОРИЗАЦИЯ:** Возьми каждое найденное мероприятие и тщательно сравни его с критериями поиска клиента. Используй контекст и семантическое понимание (например, 'мороженое' относится к 'пищевой промышленности').\n"
            "    -   Если мероприятие **полностью совпадает** с критериями (отрасль, страна, И ТОЧНОЕ СОВПАДЕНИЕ МЕСЯЦА в периоде) — помести его в массив `perfect_matches`.\n"  # <-- ИЗМЕНЕНИЕ ЗДЕСЬ
            "    -   Если страна и отрасль подходят, но дата в пределах ±3 месяцев от запрошенной (но не в том же месяце) — помести его в массив `near_date_matches`.\n"
            "    -   Все остальные найденные мероприятия помести в массив `other_mismatches`.\n"
            "3.  **ОБОСНОВАНИЕ:** Для каждого мероприятия в `near_date_matches` и `other_mismatches` ОБЯЗАТЕЛЬНО добавь ключ `mismatch_reason` с кратким и четким объяснением, почему оно не подошло.\n\n"
            "**ПРАВИЛА ФОРМАТА ОТВЕТА:**\n"
            "-   Твой ответ должен быть **ТОЛЬКО ОДНИМ JSON-объектом** и больше ничего.\n"
            "-   JSON-объект должен содержать ровно три ключа: `perfect_matches`, `near_date_matches`, `other_mismatches`. Значения этих ключей — массивы JSON-объектов мероприятий.\n"
            "-   В ключ `description` включай только самую суть (1-2 предложения), не нужно копировать большие тексты.\n"
            "-   Если в каком-то фрагменте текста есть ссылка на источник, ОБЯЗАТЕЛЬНО добавь ее в ключ `source`.\n\n"
            "**ПРИМЕР РАБОТЫ:**\n"
            "Если клиент ищет `{'industry': 'Пищевая промышленность', 'period': 'октябрь 2025'}` и ты нашел в тексте:\n"
            "-   'Indian Ice-cream Congress' на '6-8 октября 2025' (ты должен понять, что мороженое — это пищевая промышленность).\n"
            "-   'World Food India' на '25-28 сентября 2025'.\n"
            "-   'AgroTech Expo' на '15 октября 2025'.\n"
            "Твой итоговый JSON должен выглядеть так:\n"
            "```json\n"
            "{\n"
            '  "perfect_matches": [\n'
            "    {\n"
            '      "name": "Indian Ice-cream Congress",\n'
            '      "dates": "6-8 октября 2025",\n'
            '      "location": "Нью-Дели, Индия",\n'
            '      "description": "Конгресс и выставка для производителей мороженого.",\n'
            '      "source": "https://example.com/ice_cream_expo"\n'
            "    }\n"
            "  ],\n"
            '  "near_date_matches": [\n'
            "    {\n"
            '      "name": "World Food India",\n'
            '      "dates": "25-28 сентября 2025",\n'
            '      "location": "Нью-Дели, Индия",\n'
            '      "description": "Крупнейшая выставка продуктов питания.",\n'
            '      "mismatch_reason": "Мероприятие в сентябре, а не в октябре",\n'
            '      "source": "https://example.com/world_food"\n'
            "    }\n"
            "  ],\n"
            '  "other_mismatches": [\n'
            "    {\n"
            '      "name": "AgroTech Expo",\n'
            '      "dates": "15 октября 2025",\n'
            '      "location": "Мумбаи, Индия",\n'
            '      "description": "Выставка агротехнологий.",\n'
            '      "mismatch_reason": "Отрасль: Сельское хозяйство, а не Пищевая промышленность",\n'
            '      "source": "https://example.com/agrotech"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```"
        )

        combined_text = "\n\n--- ФРАГМЕНТ ТЕКСТА ---\n\n".join(chunks)

        human_prompt = (
            "Вот критерии поиска от клиента и фрагменты текста для анализа. Выполни задачу согласно твоему алгоритму.\n\n"
            f"**Критерии поиска:**\n{criteria_json}\n\n"
            f"**Фрагменты текста для анализа:**\n{combined_text}"
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]

        try:
            token_logger = TokenUsageLogger()
            response = await asyncio.to_thread(
                client.invoke, messages, config={"callbacks": [token_logger]}
            )
            content = response.content.strip()
            clean_content = content.replace("```json", "").replace("```", "").strip()

            try:
                parsed_json = json.loads(clean_content)
                if isinstance(parsed_json, dict) and all(
                    k in parsed_json for k in empty_result.keys()
                ):
                    logger.info(
                        f"GigaChat успешно извлек и категоризировал мероприятия. Perfect: {len(parsed_json.get('perfect_matches',[]))}, Near: {len(parsed_json.get('near_date_matches',[]))}, Other: {len(parsed_json.get('other_mismatches',[]))}"
                    )
                    return parsed_json
                else:
                    logger.warning(
                        f"GigaChat вернул JSON, но его структура неверна: {clean_content}"
                    )
                    return empty_result
            except json.JSONDecodeError as e:
                logger.error(
                    f"Ошибка декодирования JSON от GigaChat: {e}\nОтвет был: {content}"
                )
                return empty_result
        except Exception as e:
            logger.error(f"Критическая ошибка при вызове GigaChat: {e}", exc_info=True)
            return empty_result

    async def get_contextual_answer(
        self, user_question: str, events_context: List[Dict]
    ) -> str:
        client = self._get_client("nlu")  # Используем те же настройки, что и для NLU

        context_str = json.dumps(events_context, ensure_ascii=False, indent=2)

        system_prompt = (
            "Ты — профессиональный консультант по международным бизнес-мероприятиям. Тебе предоставлен список мероприятий, которые были найдены для клиента, и его вопрос по этому списку.\n\n"
            "Твоя задача — дать краткий, вежливый и информативный ответ на вопрос клиента, основываясь **только на предоставленном контексте**.\n\n"
            "ПРАВИЛА:\n"
            "1. Не выдумывай информацию. Если в контексте нет ответа, вежливо сообщи об этом.\n"
            "2. Отвечай как эксперт: четко, по делу и дружелюбно.\n"
            "3. Не упоминай, что тебе предоставлен 'контекст' или 'список'. Общайся естественно."
        )

        human_prompt = (
            f"**Контекст (найденные мероприятия):**\n{context_str}\n\n"
            f'**Вопрос клиента:**\n"{user_question}"\n\n'
            "**Твой ответ:**"
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]

        try:
            token_logger = TokenUsageLogger()
            response = await asyncio.to_thread(
                client.invoke, messages, config={"callbacks": [token_logger]}
            )
            return response.content.strip()
        except Exception as e:
            logger.error(
                f"Ошибка при получении контекстного ответа от GigaChat: {e}",
                exc_info=True,
            )
            return "К сожалению, произошла ошибка при обработке вашего вопроса."

    # Функция detect_change_request остается без изменений
    async def detect_change_request(
        self, text: str, current_params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        client = self._get_client("nlu")
        system_prompt = (
            "Твоя задача — проанализировать запрос пользователя и определить, хочет ли он изменить параметры поиска мероприятий. Текущие параметры поиска уже заданы.\n\n"
            "ПРАВИЛА:\n"
            "1. Внимательно изучи сообщение пользователя и определи, упоминает ли он новую страну или новый тип мероприятия.\n"
            "2. Твой ответ должен быть СТРОГО в формате JSON-объекта.\n"
            '3. В JSON-объекте могут быть только два ключа: "country" и "event_type".\n'
            "4. Если пользователь указывает новое значение для параметра, подставь его в соответствующий ключ. Если какой-то из параметров не меняется, НЕ включай его в JSON.\n"
            "5. Если в запросе пользователя нет намерения изменить ни страну, ни тип мероприятия, верни пустой JSON-объект `{}`.\n"
            "6. Не выдумывай информацию. Извлекай только те данные, которые явно присутствуют в запросе."
        )
        human_prompt = (
            f"Проанализируй следующий запрос пользователя с учетом текущих параметров поиска.\n\n"
            f"Текущие параметры: {json.dumps(current_params, ensure_ascii=False)}\n"
            f'Запрос пользователя: "{text}"\n\n'
            "Верни JSON с изменениями согласно правилам."
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
        try:
            token_logger = TokenUsageLogger()
            response = await asyncio.to_thread(
                client.invoke, messages, config={"callbacks": [token_logger]}
            )
            content = response.content.strip().lower()
            if "country" in content or "event_type" in content:
                try:
                    json_str_match = json.loads(
                        content[content.find("{") : content.rfind("}") + 1]
                    )
                    return json_str_match
                except (json.JSONDecodeError, IndexError):
                    logger.warning(f"Не удалось извлечь JSON из ответа NLU: {content}")
                    return None
            else:
                return None
        except Exception as e:
            logger.error(
                f"Ошибка при определении намерения пользователя: {e}", exc_info=True
            )
            return None


gigachat_service = GigaChatService()

# --- КОНЕЦ ОБНОВЛЕННОГО ФАЙЛА ---
