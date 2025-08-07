# --- НАЧАЛО КОДА ДЛЯ event_search_service.py ---

import logging
import asyncio
import os
from playwright.async_api import async_playwright, Error as PlaywrightError
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple
import re
from datetime import datetime, timedelta
import dateparser

from langchain_community.vectorstores import FAISS

# --- ИЗМЕНЕНИЕ: Используем новый пакет для эмбеддингов ---
from langchain_huggingface import HuggingFaceEmbeddings

# --- ИЗМЕНЕНИЕ: Импортируем класс Document ---
from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from src.nlu.gigachat_client import gigachat_service
from src.config import settings

logger = logging.getLogger(__name__)

try:
    logger.info("Загрузка модели эмбеддингов sentence-transformers...")
    # --- ИЗМЕНЕНИЕ: Используем новый класс HuggingFaceEmbeddings ---
    embedding_model = HuggingFaceEmbeddings(
        model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        model_kwargs={"device": "cpu"},
    )
    logger.info("Модель эмбеддингов успешно загружена.")
except Exception as e:
    logger.critical(f"Не удалось загрузить модель эмбеддингов! {e}", exc_info=True)
    embedding_model = None

# ... (остальные функции до _scrape_page_text без изменений) ...

USER_DATA_DIR = os.path.join(settings.BASE_DIR, "playwright_session")
HEADLESS_MODE = True


async def _search_yandex_links(
    query: str, max_results: int = 7
) -> List[Dict[str, str]]:
    """
    Выполняет поиск в Яндексе и возвращает список ссылок.
    Изменено: добавлена отказоустойчивость. Ошибка в одном запросе
    больше не прерывает всю операцию.
    """
    logger.info(f"Начинаю веб-поиск по запросу: '{query}'")
    html_content = None
    try:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                USER_DATA_DIR,
                headless=HEADLESS_MODE,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            page = await context.new_page()
            search_url = f"https://yandex.ru/search/?text={query.replace(' ', '+')}"

            # --- ИЗМЕНЕНИЕ: Внутренний блок try/except для отказоустойчивости ---
            try:
                await page.goto(
                    search_url, wait_until="domcontentloaded", timeout=60000
                )
                # Ждем именно появления результатов, это надежнее
                await page.wait_for_selector("li.serp-item", timeout=20000)
                html_content = await page.content()
            except PlaywrightError as e:
                # Эта ошибка теперь не фатальна для всей функции
                screenshot_path = os.path.join(
                    settings.BASE_DIR,
                    f"debug_screenshot_{re.sub('[^a-zA-Z0-9]', '_', query)[:50]}.png",
                )
                try:
                    await page.screenshot(path=screenshot_path)
                    logger.error(
                        f"Ошибка Playwright при обработке запроса '{query}': {e}. Скриншот сохранен в {screenshot_path}"
                    )
                except Exception as screenshot_error:
                    logger.error(
                        f"Ошибка Playwright при обработке запроса '{query}': {e}. Не удалось сохранить скриншот: {screenshot_error}"
                    )
            # --- КОНЕЦ ИЗМЕНЕНИЯ ---
            finally:
                await context.close()

    except Exception as e:
        # Этот блок теперь будет ловить только критические ошибки запуска Playwright
        logger.critical(
            f"Критическая ошибка при запуске Playwright для запроса '{query}': {e}",
            exc_info=True,
        )
        return []

    if not html_content:
        logger.warning(
            f"Не удалось получить содержимое страницы для запроса '{query}'."
        )
        return []

    soup = BeautifulSoup(html_content, "lxml")
    results = []
    search_items = soup.select("li.serp-item")

    for item in search_items:
        if len(results) >= max_results:
            break
        if "yabs.yandex.ru" in str(item) or item.select_one(".label_type_ad"):
            continue
        title_tag, link_tag = item.select_one(
            "h2, .organic__title, .Title"
        ), item.select_one("a.Link, a.organic__url")
        if title_tag and link_tag and link_tag.has_attr("href"):
            title, link = title_tag.get_text(strip=True), link_tag["href"]
            if title and link.startswith("http"):
                results.append({"title": title, "link": link})

    logger.info(f"Найдено {len(results)} ссылок в поиске по запросу '{query}'.")
    return results


async def _scrape_page_text(url: str) -> List[str]:
    logger.info(f"Начинаю извлечение текста со страницы: {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=45000)
            except PlaywrightError:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html_content = await page.content()
            await browser.close()
        soup = BeautifulSoup(html_content, "lxml")
        tags_to_remove = [
            "script",
            "style",
            "header",
            "footer",
            "nav",
            "aside",
            "form",
            "button",
            "iframe",
            "noindex",
        ]
        for element in soup(tags_to_remove):
            element.decompose()
        main_content = (
            soup.select_one("article, main, .entry-content, #content, [role='main']")
            or soup.body
        )
        text = main_content.get_text(separator="\n", strip=True) if main_content else ""
        return [text] if text else []
    except Exception as e:
        logger.error(f"Не удалось извлечь текст с {url}: {e}")
        return []


def _generate_search_queries(search_params: Dict[str, any]) -> List[str]:
    """
    Генерирует разнообразные поисковые запросы на основе параметров пользователя
    для максимального охвата источников.
    """
    industry = search_params.get("industry", "")
    country = search_params.get("country", "")
    period = search_params.get("period", "")
    event_type = search_params.get("event_type", "мероприятия")

    # Получаем год из периода для более общих запросов
    year_match = re.search(r"\b(20\d{2})\b", period)
    year = year_match.group(1) if year_match else datetime.now().year

    queries = []

    # 1. Основной, самый детальный запрос
    if industry and country and period and event_type:
        queries.append(f"{event_type} {industry} {country} {period}")

    # 2. Более общий запрос, без конкретного типа мероприятия
    if industry and country and period:
        queries.append(f"бизнес мероприятия {industry} {country} {period}")

    # 3. Запрос на английском языке (упрощенный, но эффективный)
    # Предполагаем, что базовые термины будут понятны поисковику
    if industry and country:
        industry_en = industry.replace("промышленность", "industry").replace(
            "пищевая", "food"
        )
        queries.append(f"{industry_en} exhibition conference {country} {year}")

    # 4. Запросы к специализированным сайтам-агрегаторам
    if industry and country:
        queries.append(f"site:expomap.ru {industry} {country} {year}")
        queries.append(f"site:expocentre.ru {industry} {country} {year}")
        queries.append(f"site:events.ved.gov.ru {industry} {country} {year}")

    # 5. Общий запрос на календарь событий
    if country and year:
        queries.append(f"календарь выставок {country} {year}")

    # Удаляем дубликаты и пустые строки, если таковые появятся
    unique_queries = sorted(list(set(filter(None, queries))))
    logger.info(f"Сгенерировано {len(unique_queries)} уникальных поисковых запросов.")
    return unique_queries


# --- ГЛАВНАЯ ФУНКЦИЯ ПОИСКА, ИЗМЕНЕНА ЛОГИКА ВЕКТОРНОГО ПОИСКА ---
async def find_and_summarize_events(search_params: Dict[str, any]) -> Dict[str, any]:
    """
    Выполняет поиск, делегирует анализ и категоризацию LLM,
    и возвращает готовый результат.
    """
    # Структура для возврата в случае ранней ошибки
    error_results = {
        "total_links_analyzed": 0,
        "error_message": None,
        "perfect_matches": [],
        "near_date_matches": [],
        "other_mismatches": [],
    }

    if not embedding_model:
        logger.critical("Модель для обработки текста не загружена!")
        error_results["error_message"] = (
            "Критическая ошибка: модель для обработки текста не загружена."
        )
        return error_results

    # Шаги 1-5 (сбор данных и векторный поиск) остаются практически без изменений
    queries = _generate_search_queries(search_params)
    if not queries:
        error_results["error_message"] = "Не удалось сформировать поисковые запросы."
        return error_results

    search_tasks = [_search_yandex_links(q) for q in queries]
    link_results_lists = await asyncio.gather(*search_tasks)
    all_links_map = {
        link_info["link"]: link_info["title"]
        for link_list in link_results_lists
        for link_info in link_list
    }

    if not all_links_map:
        error_results["error_message"] = (
            "К сожалению, по вашему запросу не удалось найти релевантных страниц в поиске."
        )
        return error_results

    unique_links = list(all_links_map.keys())
    total_links_analyzed = len(unique_links)
    logger.info(f"Собрано {total_links_analyzed} уникальных ссылок для анализа.")

    scraping_tasks = [_scrape_page_text(link) for link in unique_links]
    scraped_pages_with_links = zip(await asyncio.gather(*scraping_tasks), unique_links)

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=250)
    all_docs_with_metadata = []
    for page_texts, source_link in scraped_pages_with_links:
        if page_texts and page_texts[0].strip():
            chunks = text_splitter.split_text(page_texts[0])
            for chunk in chunks:
                # Добавляем источник прямо в текст чанка, чтобы LLM было легче его найти
                chunk_with_source = f"ИСТОЧНИК: {source_link}\n\nТЕКСТ: {chunk}"
                all_docs_with_metadata.append(
                    Document(
                        page_content=chunk_with_source, metadata={"source": source_link}
                    )
                )

    if not all_docs_with_metadata:
        error_results["error_message"] = (
            "Не удалось извлечь текстовое содержимое с найденных страниц."
        )
        error_results["total_links_analyzed"] = total_links_analyzed
        return error_results

    logger.info(
        f"Всего получено {len(all_docs_with_metadata)} чанков-документов для анализа."
    )

    try:
        vector_store = await asyncio.to_thread(
            FAISS.from_documents,
            documents=all_docs_with_metadata,
            embedding=embedding_model,
        )
        vector_search_query = " ".join(
            filter(
                None,
                [
                    search_params.get("event_type"),
                    search_params.get("industry"),
                    search_params.get("country"),
                    search_params.get("period"),
                ],
            )
        )

        relevant_docs = await asyncio.to_thread(
            vector_store.similarity_search, vector_search_query, k=60
        )

        if not relevant_docs:
            error_results["error_message"] = (
                "Анализ текста не выявил релевантных фрагментов."
            )
            error_results["total_links_analyzed"] = total_links_analyzed
            return error_results

        logger.debug("--- НАЧАЛО ЧАНКОВ ДЛЯ АНАЛИЗА В LLM ---")
        for i, doc in enumerate(relevant_docs):
            logger.debug(f"ЧАНК #{i+1} (Источник: {doc.metadata.get('source', 'N/A')})")
            logger.debug(doc.page_content)
            logger.debug("---")
        logger.debug("--- КОНЕЦ ЧАНКОВ ДЛЯ АНАЛИЗА В LLM ---")

        relevant_chunks_for_llm = [doc.page_content for doc in relevant_docs]

    except Exception as e:
        logger.error(f"Ошибка при векторном поиске: {e}", exc_info=True)
        error_results["error_message"] = "Произошла ошибка на этапе анализа текста."
        error_results["total_links_analyzed"] = total_links_analyzed
        return error_results

    # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Вся аналитика делегируется GigaChat ---
    # Python больше не анализирует и не фильтрует. Он просто передает данные.
    categorized_results = await gigachat_service.extract_and_categorize_events(
        chunks=relevant_chunks_for_llm, search_params=search_params
    )

    # Добавляем мета-информацию и возвращаем готовый результат
    categorized_results["total_links_analyzed"] = total_links_analyzed

    logger.info(f"Поиск и анализ LLM завершен.")

    return categorized_results


# --- КОНЕЦ КОДА ДЛЯ event_search_service.py ---
