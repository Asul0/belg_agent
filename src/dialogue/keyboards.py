from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_event_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Выставки", callback_data="event_type_exhibitions"),
            InlineKeyboardButton("Конференции", callback_data="event_type_conferences"),
        ],
        [
            InlineKeyboardButton("Деловые миссии", callback_data="event_type_missions"),
            InlineKeyboardButton(
                "Семинары/Вебинары", callback_data="event_type_seminars"
            ),
        ],
        [
            InlineKeyboardButton("Все вместе", callback_data="event_type_all"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_event_format_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Онлайн", callback_data="event_format_online"),
            InlineKeyboardButton("Офлайн", callback_data="event_format_offline"),
        ],
        [
            InlineKeyboardButton("Платно", callback_data="event_format_paid"),
            InlineKeyboardButton("Бесплатно", callback_data="event_format_free"),
        ],
        [
            InlineKeyboardButton(
                "Не важно / Пропустить", callback_data="event_format_any"
            ),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Да, все верно. Начать поиск", callback_data="confirm_search"
            ),
        ],
        [
            InlineKeyboardButton("✏️ Изменить параметры", callback_data="edit_params"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_search"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# --- НАЧАЛО НОВОГО КОДА ---


def get_alternative_search_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с вариантами действий после неудачного поиска.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "🌍 Искать в другой стране", callback_data="alt_search_new_country"
            ),
        ],
        [
            InlineKeyboardButton(
                "🗓️ Расширить период (весь год)",
                callback_data="alt_search_expand_period",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Начать новый поиск с нуля", callback_data="alt_search_start_over"
            ),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# --- КОНЕЦ НОВОГО КОДА ---
