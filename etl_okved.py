"""
ETL скрипт для импорта справочника ОКВЭД в SQLite базу данных
"""
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime


class OkvedETL:
    def __init__(self, db_name='data_storage.db', excel_file='okved.xlsx'):
        self.db_name = db_name
        self.excel_file = excel_file
        self.conn = None
    
    def connect(self):
        """Подключение к базе данных"""
        self.conn = sqlite3.connect(self.db_name)
        print(f"✓ Подключено к базе данных: {self.db_name}")
        return self.conn
    
    def close(self):
        """Закрытие соединения"""
        if self.conn:
            self.conn.close()
            print("✓ Соединение закрыто")
    
    def create_okved_table(self):
        """Создание таблицы ОКВЭД"""
        cursor = self.conn.cursor()
        
        # Удаление таблицы если она существует
        cursor.execute('DROP TABLE IF EXISTS okved')
        print("✓ Старая таблица okved удалена")
        
        # Создание таблицы
        cursor.execute('''
            CREATE TABLE okved (
                number INTEGER,
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                import_timestamp TEXT
            )
        ''')
        
        # Создание индекса по коду ОКВЭД
        cursor.execute('CREATE INDEX idx_okved_code ON okved(code)')
        
        self.conn.commit()
        print("✓ Таблица okved создана")
    
    def load_okved_data(self):
        """Загрузка данных из Excel файла"""
        if not Path(self.excel_file).exists():
            print(f"✗ Файл {self.excel_file} не найден!")
            return False
        
        print(f"\n→ Чтение файла {self.excel_file}...")
        
        try:
            # Чтение Excel файла
            df = pd.read_excel(self.excel_file)
            
            print(f"✓ Прочитано {len(df)} строк")
            print(f"  Колонки: {df.columns.tolist()}")
            
            # Переименование колонок для базы данных
            df.columns = ['number', 'code', 'name']
            
            # Добавление timestamp импорта
            df['import_timestamp'] = datetime.now().isoformat()
            
            # Очистка данных
            df['code'] = df['code'].astype(str).str.strip()
            df['name'] = df['name'].astype(str).str.strip()
            
            print("\n→ Загрузка данных в базу данных...")
            
            # Запись в базу данных
            df.to_sql('okved', self.conn, if_exists='append', index=False)
            
            print(f"✓ Данные успешно загружены: {len(df)} записей")
            
            return True
            
        except Exception as e:
            print(f"✗ Ошибка при загрузке данных: {e}")
            return False
    
    def show_statistics(self):
        """Показать статистику по таблице ОКВЭД"""
        cursor = self.conn.cursor()
        
        print("\n" + "=" * 80)
        print("СТАТИСТИКА ТАБЛИЦЫ OKVED")
        print("=" * 80)
        
        # Общее количество записей
        cursor.execute("SELECT COUNT(*) FROM okved")
        total = cursor.fetchone()[0]
        print(f"\nВсего записей: {total:,}")
        
        # Примеры записей
        cursor.execute("""
            SELECT code, name 
            FROM okved 
            ORDER BY number 
            LIMIT 10
        """)
        
        print("\nПервые 10 записей:")
        print(f"{'Код ОКВЭД':<15} {'Название':<60}")
        print("-" * 80)
        for row in cursor.fetchall():
            name = row[1][:57] + "..." if len(row[1]) > 60 else row[1]
            print(f"{row[0]:<15} {name:<60}")
        
        # Уровни вложенности
        cursor.execute("""
            SELECT 
                LENGTH(code) - LENGTH(REPLACE(code, '.', '')) as level_dots,
                COUNT(*) as count
            FROM okved
            GROUP BY level_dots
            ORDER BY level_dots
        """)
        
        print("\nРаспределение по уровням вложенности:")
        print(f"{'Уровень':<15} {'Количество':<15}")
        print("-" * 80)
        for row in cursor.fetchall():
            level = row[0] + 1
            print(f"Уровень {level:<7} {row[1]:<15,}")
        
        print("=" * 80)
    
    def test_queries(self):
        """Тестовые запросы к таблице"""
        print("\n" + "=" * 80)
        print("ПРИМЕРЫ ЗАПРОСОВ")
        print("=" * 80)
        
        cursor = self.conn.cursor()
        
        # Поиск по коду
        print("\n1. Поиск кода '01.11':")
        cursor.execute("SELECT code, name FROM okved WHERE code = '01.11'")
        result = cursor.fetchone()
        if result:
            print(f"   {result[0]}: {result[1]}")
        
        # Поиск по названию
        print("\n2. Поиск по слову 'Производство' (первые 5):")
        cursor.execute("""
            SELECT code, name 
            FROM okved 
            WHERE name LIKE '%Производство%' 
            LIMIT 5
        """)
        for row in cursor.fetchall():
            name = row[1][:60] + "..." if len(row[1]) > 60 else row[1]
            print(f"   {row[0]}: {name}")
        
        # Коды верхнего уровня
        print("\n3. Коды верхнего уровня (разделы):")
        cursor.execute("""
            SELECT code, name 
            FROM okved 
            WHERE code NOT LIKE '%.%'
            ORDER BY code
            LIMIT 10
        """)
        for row in cursor.fetchall():
            name = row[1][:55] + "..." if len(row[1]) > 55 else row[1]
            print(f"   {row[0]:<5}: {name}")
        
        print("=" * 80)


def main():
    """Основная функция"""
    print("=" * 80)
    print("ETL: ИМПОРТ СПРАВОЧНИКА ОКВЭД В SQLITE")
    print("=" * 80)
    
    etl = OkvedETL()
    
    try:
        # Подключение к базе данных
        etl.connect()
        
        # Создание таблицы
        etl.create_okved_table()
        
        # Загрузка данных
        success = etl.load_okved_data()
        
        if success:
            # Показать статистику
            etl.show_statistics()
            
            # Примеры запросов
            etl.test_queries()
            
            print(f"\n✓ Импорт завершен успешно!")
        else:
            print(f"\n✗ Импорт завершен с ошибками")
    
    except Exception as e:
        print(f"\n✗ Критическая ошибка: {e}")
        raise
    
    finally:
        etl.close()


if __name__ == "__main__":
    main()

