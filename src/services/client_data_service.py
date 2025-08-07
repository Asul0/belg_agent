import pandas as pd
import logging
import os
from typing import Dict, Optional

from src.config import settings

logger = logging.getLogger(__name__)

class ClientDataService:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.df = self._load_database()

    def _load_database(self) -> Optional[pd.DataFrame]:
        try:
            if not os.path.exists(self.file_path):
                logger.error(f"Файл базы данных не найден по пути: {self.file_path}")
                return None
            
            df = pd.read_excel(self.file_path, dtype={'ИНН': str})
            
            required_columns = ['ИНН', 'Клиент', 'Отрасль_ОКК']
            if not all(col in df.columns for col in required_columns):
                logger.error(f"В файле отсутствуют необходимые колонки: {required_columns}")
                return None
                
            logger.info(f"База данных клиентов успешно загружена. Записей: {len(df)}")
            return df
        except Exception as e:
            logger.critical(f"Критическая ошибка при загрузке базы данных клиентов: {e}", exc_info=True)
            return None

    def get_client_info_by_inn(self, inn: str) -> Optional[Dict[str, str]]:
        if self.df is None:
            logger.warning("Попытка поиска по ИНН, но база данных не загружена.")
            return None

        inn = str(inn).strip()
        client_record = self.df[self.df['ИНН'] == inn]

        if not client_record.empty:
            record = client_record.iloc[0]
            client_info = {
                "name": record['Клиент'],
                "industry": record['Отрасль_ОКК']
            }
            logger.info(f"Найден клиент по ИНН {inn}: {client_info}")
            return client_info
        else:
            logger.warning(f"ИНН {inn} не найден в базе данных.")
            return None

client_data_service = ClientDataService(settings.CLIENT_DATABASE_PATH)