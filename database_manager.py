"""
Менеджер базы данных SQLite - импорт CSV и работа с данными
"""
import sqlite3
import pandas as pd
import os
from pathlib import Path
from datetime import datetime
import sys


class DatabaseManager:
    def __init__(self, db_name='data_storage.db'):
        self.db_name = db_name
        self.conn = None
        self.identifier_db_name = 'identifier.sqlite'
    
    def connect(self):
        """Подключение к базе данных"""
        self.conn = sqlite3.connect(self.db_name)
        return self.conn
    
    def connect_to_identifier_db(self):
        """Подключение к базе данных identifier.sqlite (создается автоматически, если не существует)"""
        if self.conn:
            self.close()
        self.conn = sqlite3.connect(self.identifier_db_name)
        print(f"✓ Подключено к базе данных: {self.identifier_db_name}")
        return self.conn
    
    def connect_to_db(self, db_name):
        """Подключение к указанной базе данных"""
        if self.conn:
            self.close()
        self.conn = sqlite3.connect(db_name)
        print(f"✓ Подключено к базе данных: {db_name}")
        return self.conn
    
    def close(self):
        """Закрытие соединения"""
        if self.conn:
            self.conn.close()
    
    def create_schema(self):
        """Создание таблицы в SQLite базе данных"""
        cursor = self.conn.cursor()
        
        # Удаление таблицы если она существует
        cursor.execute('DROP TABLE IF EXISTS data_table')
        print("✓ Старая таблица удалена")
        
        cursor.execute('''
            CREATE TABLE data_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_lvl_1 TEXT,
                id_lvl_2 TEXT,
                parameter_id INTEGER,
                fact_amt REAL,
                fact_amt_2 REAL,
                field_1_value_s TEXT,
                field_3_value_s TEXT,
                field_4_value_s TEXT,
                field_5_value_s TEXT,
                field_6_value_s TEXT,
                field_7_value_s TEXT,
                field_8_value_s TEXT,
                field_9_value_s TEXT,
                field_10_value_s TEXT,
                field_11_value_n REAL,
                field_12_value_n REAL,
                field_13_value_d TEXT,
                load_id INTEGER,
                load_date TEXT,
                field_2_value_s TEXT,
                date_act TEXT,
                import_timestamp TEXT
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_parameter_id ON data_table(parameter_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_load_date ON data_table(load_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date_act ON data_table(date_act)')
        
        self.conn.commit()
        print("✓ Схема базы данных создана")
    
    def import_csv_files(self, source_folder='csv', batch_size=10000):
        """Импорт всех CSV файлов из папки в базу данных"""
        source_path = Path(source_folder)
        
        if not source_path.exists():
            print(f"✗ Папка {source_folder} не найдена!")
            return
        
        csv_files = sorted(source_path.glob('output_excel_part_*.csv'))
        
        if not csv_files:
            print(f"✗ CSV файлы не найдены в папке {source_folder}")
            return
        
        print(f"\nНайдено {len(csv_files)} CSV файлов")
        print("-" * 60)
        
        total_rows = 0
        import_timestamp = datetime.now().isoformat()
        
        for idx, csv_file in enumerate(csv_files, 1):
            print(f"\n[{idx}/{len(csv_files)}] Обработка: {csv_file.name}")
            
            try:
                chunk_iterator = pd.read_csv(
                    csv_file,
                    chunksize=batch_size,
                    encoding='utf-8',
                    low_memory=False
                )
                
                file_rows = 0
                for chunk_num, chunk in enumerate(chunk_iterator, 1):
                    chunk['import_timestamp'] = import_timestamp
                    
                    # Вставка меньшими порциями для избежания ошибки "too many SQL variables"
                    mini_batch_size = 500
                    for i in range(0, len(chunk), mini_batch_size):
                        mini_chunk = chunk.iloc[i:i+mini_batch_size]
                        mini_chunk.to_sql(
                            'data_table',
                            self.conn,
                            if_exists='append',
                            index=False
                        )
                    
                    file_rows += len(chunk)
                    print(f"  └─ Chunk {chunk_num}: {len(chunk):,} строк | Всего: {file_rows:,}")
                
                total_rows += file_rows
                print(f"  ✓ Импортировано: {file_rows:,} строк")
                
            except Exception as e:
                print(f"  ✗ Ошибка при обработке файла: {e}")
                continue
        
        print("\n" + "=" * 60)
        print(f"✓ ИМПОРТ ЗАВЕРШЕН")
        print(f"  Всего импортировано: {total_rows:,} строк")
        print(f"  Обработано файлов: {len(csv_files)}")
        print("=" * 60)
    
    def show_table_info(self):
        """Показать информацию о таблице"""
        cursor = self.conn.cursor()
        
        print("\n" + "=" * 80)
        print("СТРУКТУРА ТАБЛИЦЫ data_table")
        print("=" * 80)
        
        cursor.execute("PRAGMA table_info(data_table)")
        columns = cursor.fetchall()
        
        print(f"{'№':<4} {'Название':<25} {'Тип':<15} {'Null':<6} {'Default':<10}")
        print("-" * 80)
        for col in columns:
            cid, name, col_type, not_null, default_val, pk = col
            null_str = "NO" if not_null else "YES"
            default_str = str(default_val) if default_val else "-"
            print(f"{cid:<4} {name:<25} {col_type:<15} {null_str:<6} {default_str:<10}")
        print("=" * 80)
    
    def show_statistics(self):
        """Показать статистику по данным"""
        cursor = self.conn.cursor()
        
        print("\n" + "=" * 80)
        print("СТАТИСТИКА ДАННЫХ")
        print("=" * 80)
        
        cursor.execute("SELECT COUNT(*) FROM data_table")
        total = cursor.fetchone()[0]
        print(f"\nВсего записей: {total:,}")
        
        cursor.execute("""
            SELECT 
                parameter_id,
                COUNT(*) as count,
                ROUND(AVG(fact_amt), 2) as avg_fact_amt
            FROM data_table 
            WHERE parameter_id IS NOT NULL
            GROUP BY parameter_id 
            ORDER BY count DESC 
            LIMIT 10
        """)
        
        print("\n10 самых частых parameter_id:")
        print(f"{'Parameter ID':<15} {'Количество':<15} {'Средний fact_amt':<20}")
        print("-" * 80)
        for row in cursor.fetchall():
            print(f"{row[0]:<15} {row[1]:<15,} {row[2]:<20}")
        
        cursor.execute("""
            SELECT 
                date_act,
                COUNT(*) as count
            FROM data_table 
            WHERE date_act IS NOT NULL AND date_act != ''
            GROUP BY date_act 
            ORDER BY date_act DESC
            LIMIT 10
        """)
        
        print("\nРаспределение по date_act (последние 10):")
        print(f"{'Дата':<15} {'Количество записей':<20}")
        print("-" * 80)
        for row in cursor.fetchall():
            print(f"{row[0]:<15} {row[1]:<20,}")
        
        cursor.execute("""
            SELECT 
                field_1_value_s,
                COUNT(*) as count
            FROM data_table 
            WHERE field_1_value_s IS NOT NULL AND field_1_value_s != ''
            GROUP BY field_1_value_s 
            ORDER BY count DESC 
            LIMIT 5
        """)
        
        print("\nТоп-5 значений field_1_value_s:")
        print(f"{'Значение':<30} {'Количество':<20}")
        print("-" * 80)
        for row in cursor.fetchall():
            value = row[0][:27] + "..." if len(row[0]) > 30 else row[0]
            print(f"{value:<30} {row[1]:<20,}")
        
        print("=" * 80)
    
    def export_sample_to_csv(self, output_file='sample_data.csv', limit=1000):
        """Экспортировать образец данных в CSV"""
        query = f"SELECT * FROM data_table LIMIT {limit}"
        df = pd.read_sql_query(query, self.conn)
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n✓ Образец данных ({len(df)} строк) экспортирован в: {output_file}")
    
    def custom_query(self, query):
        """Выполнить пользовательский запрос"""
        try:
            df = pd.read_sql_query(query, self.conn)
            print("\n" + "=" * 80)
            print("РЕЗУЛЬТАТЫ ЗАПРОСА")
            print("=" * 80)
            print(f"\nЗапрос: {query}")
            print(f"\nКоличество строк: {len(df)}")
            print("\nПервые 20 строк:")
            print(df.head(20).to_string())
            print("=" * 80)
            return df
        except Exception as e:
            print(f"\n✗ Ошибка выполнения запроса: {e}")
            return None
    
    def interactive_mode(self):
        """Интерактивный режим для выполнения запросов"""
        print("\n" + "=" * 80)
        print("ИНТЕРАКТИВНЫЙ РЕЖИМ")
        print("=" * 80)
        print("Введите SQL запрос (или 'exit' для выхода)")
        print("Пример: SELECT * FROM data_table WHERE parameter_id = 5 LIMIT 10")
        print("-" * 80)
        
        while True:
            query = input("\nSQL> ").strip()
            
            if query.lower() in ['exit', 'quit', 'q']:
                print("Выход из интерактивного режима")
                break
            
            if not query:
                continue
            
            self.custom_query(query)


def show_menu():
    """Показать главное меню"""
    print("\n" + "=" * 80)
    print("МЕНЕДЖЕР БАЗЫ ДАННЫХ SQLite")
    print("=" * 80)
    print("\n1. Импорт CSV файлов в базу данных")
    print("2. Показать структуру таблицы")
    print("3. Показать статистику")
    print("4. Экспортировать образец данных")
    print("5. Выполнить SQL запрос")
    print("6. Интерактивный режим SQL")
    print("7. Подключиться к identifier.sqlite")
    print("8. Переключиться на другую базу данных")
    print("0. Выход")
    print("-" * 80)


def main():
    """Основная функция"""
    # Проверка аргументов командной строки для выбора базы данных
    db_name = 'data_storage.db'
    if len(sys.argv) > 1:
        # Если первый аргумент - путь к базе данных
        if sys.argv[1].endswith('.sqlite') or sys.argv[1].endswith('.db'):
            db_name = sys.argv[1]
            sys.argv = [sys.argv[0]] + sys.argv[2:]  # Удаляем аргумент с именем БД
    
    db_manager = DatabaseManager(db_name=db_name)
    
    # Проверка аргументов командной строки
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        
        if action == 'import':
            print("=" * 80)
            print("ИМПОРТ CSV ФАЙЛОВ В SQLITE")
            print("=" * 80)
            db_manager.connect()
            db_manager.create_schema()
            db_manager.import_csv_files()
            db_manager.show_statistics()
            db_manager.close()
            return
        
        elif action == 'stats':
            if not Path(db_manager.db_name).exists():
                print(f"✗ База данных не найдена. Сначала выполните импорт.")
                return
            db_manager.connect()
            db_manager.show_statistics()
            db_manager.close()
            return
        
        elif action == 'query':
            if not Path(db_manager.db_name).exists():
                print(f"✗ База данных не найдена. Сначала выполните импорт.")
                return
            db_manager.connect()
            db_manager.interactive_mode()
            db_manager.close()
            return
        
        elif action == 'identifier' or action == 'id':
            # Работа с identifier.sqlite (создается автоматически)
            db_manager.connect_to_identifier_db()
            db_manager.interactive_mode()
            db_manager.close()
            return
    
    # Интерактивное меню
    db_exists = Path(db_manager.db_name).exists()
    current_db = db_manager.db_name
    
    while True:
        print(f"\n📊 Текущая база данных: {current_db}")
        show_menu()
        
        try:
            choice = input("\nВыберите действие: ").strip()
            
            if choice == '0':
                print("\nВыход из программы")
                break
            
            elif choice == '1':
                db_manager.connect()
                db_manager.create_schema()
                db_manager.import_csv_files()
                db_manager.close()
                db_exists = True
            
            elif choice == '2':
                if not db_exists:
                    print("\n✗ База данных не найдена. Сначала выполните импорт (пункт 1).")
                    continue
                db_manager.connect()
                db_manager.show_table_info()
                db_manager.close()
            
            elif choice == '3':
                if not db_exists:
                    print("\n✗ База данных не найдена. Сначала выполните импорт (пункт 1).")
                    continue
                db_manager.connect()
                db_manager.show_statistics()
                db_manager.close()
            
            elif choice == '4':
                if not db_exists:
                    print("\n✗ База данных не найдена. Сначала выполните импорт (пункт 1).")
                    continue
                limit = input("\nКоличество строк для экспорта (по умолчанию 1000): ").strip()
                limit = int(limit) if limit.isdigit() else 1000
                db_manager.connect()
                db_manager.export_sample_to_csv(limit=limit)
                db_manager.close()
            
            elif choice == '5':
                if not db_exists:
                    print("\n✗ База данных не найдена. Сначала выполните импорт (пункт 1).")
                    continue
                query = input("\nВведите SQL запрос: ").strip()
                if query:
                    db_manager.connect()
                    db_manager.custom_query(query)
                    db_manager.close()
            
            elif choice == '6':
                if not db_exists:
                    print("\n✗ База данных не найдена. Сначала выполните импорт (пункт 1).")
                    continue
                db_manager.connect()
                db_manager.interactive_mode()
                db_manager.close()
            
            elif choice == '7':
                # Подключение к identifier.sqlite (создается автоматически)
                db_manager.connect_to_identifier_db()
                current_db = db_manager.identifier_db_name
                print("\nДоступные таблицы:")
                cursor = db_manager.conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                if tables:
                    for table in tables:
                        print(f"  • {table[0]}")
                else:
                    print("  (нет таблиц)")
                db_manager.close()
            
            elif choice == '8':
                # Переключение на другую базу данных (создается автоматически, если не существует)
                db_path = input("\nВведите путь к базе данных (например: identifier.sqlite): ").strip()
                if db_path:
                    db_manager.connect_to_db(db_path)
                    current_db = db_path
                    db_manager.db_name = db_path  # Обновляем имя базы для менеджера
                    db_exists = Path(db_path).exists()
                    db_manager.close()
            
            else:
                print("\n✗ Неверный выбор. Попробуйте снова.")
        
        except KeyboardInterrupt:
            print("\n\nПрервано пользователем")
            break
        except Exception as e:
            print(f"\n✗ Ошибка: {e}")
    
    db_manager.close()


if __name__ == "__main__":
    main()

