# --- НАЧАЛО ФИНАЛЬНОЙ ВЕРСИИ ФАЙЛА ---

import logging
from typing import Dict, Any, Optional, List
import re
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction, ParseMode

from src.dialogue.keyboards import (
    get_event_type_keyboard,
    get_event_format_keyboard,
    get_confirmation_keyboard,
    get_alternative_search_keyboard,
)
from src.services.client_data_service import client_data_service
from src.services.event_search_service import find_and_summarize_events
from src.nlu.gigachat_client import gigachat_service

logger = logging.getLogger(__name__)


# Упрощенный санитайзер для старого Markdown
def _sanitize_markdown(text: str) -> str:
    """Экранирует базовые символы для старого Markdown."""
    if not isinstance(text, str):
        text = str(text)
    # Основные символы, которые могут сломать разметку
    escape_chars = r"([*_`\[])"
    return re.sub(escape_chars, r"\\\1", text)


class DialogueManager:
    def __init__(self):
        self.user_states: Dict[str, Dict[str, Any]] = {}

    def _get_or_create_state(self, user_id: str) -> Dict[str, Any]:
        if user_id not in self.user_states:
            self.user_states[user_id] = self._get_default_state()
        return self.user_states[user_id]

    def _get_default_state(self) -> Dict[str, Any]:
        return {
            "stage": "awaiting_inn",
            "inn": None,
            "client_name": None,
            "industry": None,
            "country": None,
            "period": None,
            "event_type": None,
            "extra_info": [],
            "last_search_results": [],  # --- НОВОЕ ПОЛЕ: для хранения контекста ---
        }

    async def _clear_state(self, user_id: str):
        current_state = self.user_states.get(user_id, {})
        new_state = self._get_default_state()
        if "inn" in current_state:
            new_state.update(
                {
                    "inn": current_state["inn"],
                    "client_name": current_state["client_name"],
                    "industry": current_state["industry"],
                    "stage": "awaiting_country",
                }
            )
        self.user_states[user_id] = new_state
        return new_state

    async def _send_typing_action(
        self, context: ContextTypes.DEFAULT_TYPE, chat_id: int
    ):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    async def start_dialogue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.first_name
        self.user_states[user_id] = self._get_default_state()

        start_message = (
            f"Здравствуйте, {user_name}!\n\n"
            "Я ваш ассистент по подбору международных бизнес-мероприятий. "
            "Чтобы я мог найти для вас наиболее подходящие варианты, пожалуйста, ответьте на несколько вопросов.\n\n"
            "Для начала, введите ИНН вашей компании."
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(
                f"Давайте начнем сначала. Введите ИНН вашей компании."
            )
        else:
            await update.message.reply_text(start_message)

    async def handle_text_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id
        text = update.message.text.strip()
        state = self._get_or_create_state(user_id)
        await self._send_typing_action(context, chat_id)
        stage = state.get("stage")

        # --- ИЗМЕНЕНИЕ: Новая логика общения после поиска ---
        if stage == "post_search":
            # Сначала проверяем, не хочет ли пользователь изменить параметры
            change = await gigachat_service.detect_change_request(text, state)
            if change:
                state.update(change)
                state["last_search_results"] = (
                    []
                )  # Сбрасываем контекст при новом поиске
                logger.info(f"Пользователь уточнил запрос. Новые параметры: {change}")
                await context.bot.send_message(
                    chat_id, text=f"Понял, ищу с учетом новых данных: {text}"
                )
                await self._execute_search(update, context)
            # Если это не изменение параметров, а вопрос
            elif state.get("last_search_results"):
                await context.bot.send_message(
                    chat_id, text="Минутку, сейчас проанализирую ваш вопрос..."
                )
                answer = await gigachat_service.get_contextual_answer(
                    user_question=text, events_context=state["last_search_results"]
                )
                await context.bot.send_message(chat_id, text=answer)
            else:
                await update.message.reply_text(
                    "Если хотите начать новый поиск, воспользуйтесь командой /start."
                )

        elif stage == "awaiting_inn":
            if re.fullmatch(r"\d{10,12}", text):
                client_info = client_data_service.get_client_info_by_inn(text)
                if client_info:
                    state.update(
                        {
                            "inn": text,
                            "client_name": client_info["name"],
                            "industry": client_info["industry"],
                            "stage": "awaiting_country",
                        }
                    )
                    await update.message.reply_text(
                        f"Отлично, {client_info['name']}!\nТеперь укажите страну, которая вас интересует."
                    )
                else:
                    state.update({"inn": text, "stage": "awaiting_industry"})
                    await update.message.reply_text(
                        "К сожалению, не нашел такой ИНН в базе. Пожалуйста, укажите вашу отрасль."
                    )
            else:
                await update.message.reply_text(
                    "Пожалуйста, введите корректный ИНН (10 или 12 цифр)."
                )

        # Остальная логика сбора данных без изменений
        elif stage == "awaiting_industry":
            state.update({"industry": text, "stage": "awaiting_country"})
            await update.message.reply_text("Спасибо! Теперь укажите страну.")
        elif stage == "awaiting_country":
            state.update({"country": text, "stage": "awaiting_period"})
            await update.message.reply_text("Принято. Укажите интересующий вас период.")
        elif stage == "awaiting_period":
            state.update({"period": text, "stage": "awaiting_event_type"})
            await update.message.reply_text(
                "Хорошо. Какой вид мероприятия вы ищете?",
                reply_markup=get_event_type_keyboard(),
            )
        elif stage == "awaiting_new_country":
            state.update({"country": text, "stage": "awaiting_confirmation"})
            await self._show_summary_and_confirm(update.message, state, is_query=False)
        else:
            await update.message.reply_text(
                "Пожалуйста, следуйте инструкциям. Для нового поиска используйте команду /start."
            )

    async def handle_callback_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        await query.answer()
        user_id = str(query.from_user.id)
        state = self._get_or_create_state(user_id)
        stage = state.get("stage")
        data = query.data

        if stage == "awaiting_event_type":
            event_type_map = {
                "exhibitions": "выставки",
                "conferences": "конференции",
                "missions": "деловые миссии",
                "seminars": "семинары вебинары",
                "all": "мероприятия по ВЭД",
            }
            if data.startswith("event_type_"):
                state.update(
                    {
                        "event_type": event_type_map[data.split("_")[2]],
                        "stage": "awaiting_format",
                    }
                )
                await query.edit_message_text(
                    text=f"Выбрано: {state['event_type']}\n\nТеперь уточните формат участия.",
                    reply_markup=get_event_format_keyboard(),
                )
        elif stage == "awaiting_format":
            if data.startswith("event_format_"):
                format_type = data.split("_")[2]
                if format_type != "any":
                    if format_type not in state["extra_info"]:
                        state["extra_info"].append(format_type)
                    await query.edit_message_text(
                        text=f"Выбрано: {', '.join(state['extra_info'])}. Вы можете выбрать еще или нажать 'Не важно', чтобы продолжить.",
                        reply_markup=get_event_format_keyboard(),
                    )
                else:
                    state["stage"] = "awaiting_confirmation"
                    await self._show_summary_and_confirm(query, state)
        elif stage == "awaiting_confirmation":
            if data == "confirm_search":
                await query.edit_message_text(
                    text="Отлично! Начинаю поиск. Это может занять до минуты..."
                )
                await self._execute_search(update, context)
            elif data == "edit_params":
                new_state = await self._clear_state(user_id)
                text = "Давайте начнем заново. " + (
                    "Страна, которая вас интересует?"
                    if new_state.get("stage") == "awaiting_country"
                    else "Введите ИНН вашей компании."
                )
                await query.edit_message_text(text=text)
            elif data == "cancel_search":
                self.user_states[user_id] = self._get_default_state()
                await query.edit_message_text(
                    text="Поиск отменен. Для нового поиска используйте /start."
                )
        elif stage == "post_search":
            state["last_search_results"] = []  # Сбрасываем контекст при новом поиске
            if data == "alt_search_expand_period":
                current_year_match = re.search(
                    r"\b(20\d{2})\b", state.get("period", "")
                )
                current_year = (
                    current_year_match.group(1)
                    if current_year_match
                    else str(datetime.now().year)
                )
                state["period"] = f"весь {current_year} год"
                await query.edit_message_text(
                    text=f"Хорошо, ищу по всему {current_year} году..."
                )
                await self._execute_search(update, context)
            elif data == "alt_search_new_country":
                state["stage"] = "awaiting_new_country"
                await query.edit_message_text(
                    text="Понял. Введите новую страну для поиска."
                )
            elif data == "alt_search_start_over":
                await self.start_dialogue(update, context)

    async def _show_summary_and_confirm(self, query_or_message, state, is_query=True):
        summary_parts = ["*Проверьте, пожалуйста, все ли верно:*\n"]
        if state["client_name"]:
            summary_parts.append(
                f"🏢 *Компания:* {state['client_name']} (ИНН: {state['inn']})"
            )
        summary_parts.extend(
            [
                f"💡 *Отрасль:* {state['industry']}",
                f"🌍 *Страна:* {state['country']}",
                f"🗓️ *Период:* {state['period']}",
                f"📋 *Тип мероприятия:* {state['event_type']}",
            ]
        )
        if state["extra_info"]:
            summary_parts.append(
                f"⚙️ *Доп. параметры:* {', '.join(state['extra_info'])}"
            )
        summary_text = "\n".join(summary_parts)
        if is_query:
            await query_or_message.edit_message_text(
                text=summary_text,
                reply_markup=get_confirmation_keyboard(),
                parse_mode="Markdown",
            )
        else:
            await query_or_message.reply_text(
                text=summary_text,
                reply_markup=get_confirmation_keyboard(),
                parse_mode="Markdown",
            )

    # --- ИЗМЕНЕНИЕ: Добавляем вывод источника ---
    def _format_event_message(
        self, event: Dict[str, any], show_full: bool = True
    ) -> str:
        # Используем безопасный санитайзер для старого Markdown
        name = _sanitize_markdown(
            (event.get("name") or "Не указано").strip().strip("\"'")
        )
        parts = [f"*{name}*"]
        if show_full:
            parts.extend(
                [
                    f"*Даты:* {_sanitize_markdown(event.get('dates') or 'Не указаны')}",
                    f"*Место:* {_sanitize_markdown(event.get('location') or 'Не указано')}",
                ]
            )
            desc = event.get("description")
            if desc:
                parts.append(
                    f"*Описание:* {_sanitize_markdown(desc[:250] + '...' if len(desc) > 250 else desc)}"
                )

        if event.get("mismatch_reason"):
            parts.append(
                f"🔍 _Примечание: {_sanitize_markdown(event.get('mismatch_reason'))}_"
            )

        # Добавляем вывод источника
        if show_full and event.get("source"):
            parts.append(f"[Источник]({event.get('source')})")

        return "\n".join(parts)

    async def _execute_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        chat_id = update.effective_chat.id
        state = self._get_or_create_state(user_id)
        await self._send_typing_action(context, chat_id)

        status_message = None
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="Анализирую результаты..."
            )
            status_message = update.callback_query.message

        search_results = await find_and_summarize_events(state)
        state["stage"] = "post_search"

        if status_message:
            await status_message.delete()

        if search_results.get("error_message"):
            await context.bot.send_message(
                chat_id=chat_id, text=search_results["error_message"]
            )
            return

        perfect = search_results.get("perfect_matches", [])
        near_date = search_results.get("near_date_matches", [])
        mismatched = search_results.get("other_mismatches", [])
        total_links = search_results.get("total_links_analyzed", 0)

        # --- ИЗМЕНЕНИЕ: Сохраняем найденные результаты в контекст ---
        shown_events = perfect + near_date
        state["last_search_results"] = shown_events

        message_parts = []
        show_alternatives_keyboard = False

        if perfect:
            message_parts.append(
                f"✅ *Отлично! Я проанализировал {total_links} страниц и нашел точные совпадения:*"
            )
            for event in perfect:
                message_parts.append(self._format_event_message(event, show_full=True))
            if near_date:
                message_parts.append(
                    "\n"
                    + "💡 *Дополнительно:* Нашлись еще несколько крупных событий в соседние даты:"
                )
                for event in near_date[:2]:
                    message_parts.append(
                        self._format_event_message(event, show_full=False)
                    )
        elif near_date:
            message_parts.append(
                f"🤔 По вашему запросу не нашлось точных совпадений. Но я расширил поиск (проанализировано {total_links} страниц) и *нашел несколько очень релевантных вариантов в близкие даты:*"
            )
            for event in near_date:
                message_parts.append(self._format_event_message(event, show_full=True))
        else:
            show_alternatives_keyboard = True
            message_parts.append(
                f"❌ Я провел исчерпывающий поиск (проанализировано {total_links} страниц), но, к сожалению, подходящих мероприятий не нашлось."
            )
            if mismatched:
                message_parts.append(
                    "\n"
                    + "_Чтобы вы были в курсе, вот что удалось найти и почему оно не подошло под точные критерии:_"
                )
                for event in mismatched[:3]:
                    message_parts.append(
                        self._format_event_message(event, show_full=False)
                    )

        final_message = "\n\n---\n\n".join(message_parts)

        if not final_message.strip():
            final_message = (
                "Не удалось сформировать итоговое сообщение. Попробуйте снова."
            )

        for i in range(0, len(final_message), 4096):
            await context.bot.send_message(
                chat_id=chat_id, text=final_message[i : i + 4096], parse_mode="Markdown"
            )

        # --- ИЗМЕНЕНИЕ: Умное завершающее сообщение ---
        if shown_events:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Вы можете задать уточняющий вопрос по найденным мероприятиям или начать новый поиск с команды /start.",
                parse_mode="Markdown",
            )
        elif show_alternatives_keyboard:
            await context.bot.send_message(
                chat_id=chat_id,
                text="*Что можно сделать?*",
                reply_markup=get_alternative_search_keyboard(),
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Вы можете уточнить запрос (например, 'а что есть в Китае?') или начать новый поиск с команды /start.",
            )


# --- КОНЕЦ ФИНАЛЬНОЙ ВЕРСИИ ФАЙЛА ---
