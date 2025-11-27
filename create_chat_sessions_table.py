"""
Скрипт для создания таблицы chat_sessions в базе данных.
Хранит объединенные ответы пользователей из диалогов с ботом.
"""

import sqlite3
from datetime import datetime
from pathlib import Path


def create_chat_sessions_table(db_name='data_storage.db'):
    """
    Создание таблицы для хранения диалогов пользователей.
    
    Структура таблицы:
    - id: автоинкремент PRIMARY KEY
    - chat_id: ID чата в Telegram
    - session_id: уникальный номер сессии (UUID или timestamp)
    - user_response: полный диалог (вопросы бота + ответы пользователя)
    - company_info: JSON с извлеченной информацией о компании (опционально)
    - revenue_category: извлеченная категория выручки из справочника
    - created_at: дата и время создания записи
    """
    
    # Проверяем существование БД
    db_exists = Path(db_name).exists()
    
    if not db_exists:
        print(f"⚠ База данных '{db_name}' не существует. Будет создана новая.")
    
    # Подключаемся к БД
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    print("\n" + "=" * 80)
    print("СОЗДАНИЕ ТАБЛИЦЫ chat_sessions")
    print("=" * 80)
    
    # Проверяем, существует ли таблица
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='chat_sessions'
    """)
    
    table_exists = cursor.fetchone() is not None
    
    if table_exists:
        print("\n⚠ Таблица 'chat_sessions' уже существует.")
        try:
            answer = input("Пересоздать таблицу? ВСЕ ДАННЫЕ БУДУТ УДАЛЕНЫ! (yes/no): ").strip().lower()
        except EOFError:
            # Если нет интерактивного ввода, пересоздаем автоматически
            answer = 'yes'
            print("Автоматическое пересоздание таблицы...")
        
        if answer == 'yes':
            cursor.execute('DROP TABLE IF EXISTS chat_sessions')
            print("✓ Старая таблица удалена")
        else:
            print("✗ Операция отменена")
            conn.close()
            return
    
    # Создаем таблицу
    cursor.execute('''
        CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            session_id TEXT NOT NULL UNIQUE,
            user_response TEXT NOT NULL,
            company_info TEXT,
            revenue_category TEXT,
            created_at TEXT NOT NULL,
            CONSTRAINT unique_session UNIQUE (chat_id, session_id)
        )
    ''')
    
    print("✓ Таблица 'chat_sessions' создана")
    
    # Создаем индексы для быстрого поиска
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_id ON chat_sessions(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_id ON chat_sessions(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON chat_sessions(created_at)')
    
    print("✓ Индексы созданы")
    
    # Сохраняем изменения
    conn.commit()
    
    # Показываем структуру таблицы
    print("\n" + "-" * 80)
    print("СТРУКТУРА ТАБЛИЦЫ")
    print("-" * 80)
    
    cursor.execute("PRAGMA table_info(chat_sessions)")
    columns = cursor.fetchall()
    
    print(f"{'№':<4} {'Название':<20} {'Тип':<15} {'NOT NULL':<10} {'PK':<5}")
    print("-" * 80)
    for col in columns:
        cid, name, col_type, not_null, default_val, pk = col
        not_null_str = "YES" if not_null else "NO"
        pk_str = "YES" if pk else "NO"
        print(f"{cid:<4} {name:<20} {col_type:<15} {not_null_str:<10} {pk_str:<5}")
    
    print("-" * 80)
    print("\nОписание полей:")
    print("  • id            - автоинкремент, первичный ключ")
    print("  • chat_id       - ID чата в Telegram")
    print("  • session_id    - уникальный номер сессии диалога")
    print("  • user_response - полный диалог (вопросы бота + ответы пользователя)")
    print("  • company_info  - JSON с извлеченной информацией о компании")
    print("  • revenue_category - категория выручки из справочника")
    print("  • created_at    - дата и время создания записи")
    
    # Добавляем тестовую запись для примера
    print("\n" + "-" * 80)
    try:
        add_sample = input("Добавить тестовую запись для примера? (yes/no): ").strip().lower()
    except EOFError:
        # Если нет интерактивного ввода, пропускаем тестовую запись
        add_sample = 'no'
    
    if add_sample == 'yes':
        test_data = {
            'chat_id': 123456789,
            'session_id': f'session_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'user_response': 'Пользователь: Мы IT компания\nБот: Какая примерно выручка и сколько сотрудников?\nПользователь: У нас 50 человек, выручка около 100 млн в год',
            'company_info': '{"industry": "IT", "revenue": "100 млн", "staff_count": "50 человек"}',
            'revenue_category': '10-120 млн.р.',
            'created_at': datetime.now().isoformat()
        }
        
        cursor.execute('''
            INSERT INTO chat_sessions 
            (chat_id, session_id, user_response, company_info, revenue_category, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            test_data['chat_id'],
            test_data['session_id'],
            test_data['user_response'],
            test_data['company_info'],
            test_data['revenue_category'],
            test_data['created_at']
        ))
        
        conn.commit()
        print("✓ Тестовая запись добавлена")
        
        # Показываем тестовую запись
        cursor.execute("SELECT * FROM chat_sessions LIMIT 1")
        record = cursor.fetchone()
        
        print("\nПример записи:")
        print(f"  ID: {record[0]}")
        print(f"  Chat ID: {record[1]}")
        print(f"  Session ID: {record[2]}")
        print(f"  User Response: {record[3]}")
        print(f"  Company Info: {record[4]}")
        print(f"  Created At: {record[5]}")
    
    print("\n" + "=" * 80)
    print("✓ ТАБЛИЦА УСПЕШНО СОЗДАНА")
    print("=" * 80)
    
    conn.close()


def show_table_stats(db_name='data_storage.db'):
    """Показать статистику по таблице chat_sessions"""
    
    if not Path(db_name).exists():
        print(f"✗ База данных '{db_name}' не найдена")
        return
    
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    # Проверяем существование таблицы
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='chat_sessions'
    """)
    
    if not cursor.fetchone():
        print("✗ Таблица 'chat_sessions' не найдена. Сначала создайте её.")
        conn.close()
        return
    
    print("\n" + "=" * 80)
    print("СТАТИСТИКА ТАБЛИЦЫ chat_sessions")
    print("=" * 80)
    
    # Общее количество записей
    cursor.execute("SELECT COUNT(*) FROM chat_sessions")
    total = cursor.fetchone()[0]
    print(f"\nВсего записей: {total}")
    
    if total > 0:
        # Количество уникальных пользователей
        cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM chat_sessions")
        unique_users = cursor.fetchone()[0]
        print(f"Уникальных пользователей: {unique_users}")
        
        # Последние 5 записей
        cursor.execute("""
            SELECT chat_id, session_id, 
                   substr(user_response, 1, 50) as response_preview,
                   created_at
            FROM chat_sessions 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        
        print("\nПоследние 5 записей:")
        print(f"{'Chat ID':<15} {'Session ID':<25} {'Response':<50} {'Created':<25}")
        print("-" * 80)
        
        for row in cursor.fetchall():
            response = row[2] + "..." if len(row[2]) >= 50 else row[2]
            print(f"{row[0]:<15} {row[1]:<25} {response:<50} {row[3]:<25}")
    
    print("=" * 80)
    
    conn.close()


def main():
    """Главная функция"""
    import sys
    
    # Если запущен с аргументом, выполняем действие напрямую
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        if action == 'create' or action == '1':
            create_chat_sessions_table()
            return
        elif action == 'stats' or action == '2':
            show_table_stats()
            return
    
    # Интерактивный режим
    print("\n" + "=" * 80)
    print("МЕНЕДЖЕР ТАБЛИЦЫ ДИАЛОГОВ")
    print("=" * 80)
    print("\n1. Создать таблицу chat_sessions")
    print("2. Показать статистику")
    print("0. Выход")
    print("-" * 80)
    
    try:
        choice = input("\nВыберите действие: ").strip()
        
        if choice == '1':
            create_chat_sessions_table()
        elif choice == '2':
            show_table_stats()
        elif choice == '0':
            print("Выход")
        else:
            print("✗ Неверный выбор")
    except EOFError:
        # Если нет интерактивного ввода, создаем таблицу автоматически
        print("\nАвтоматическое создание таблицы...")
        create_chat_sessions_table()


if __name__ == "__main__":
    main()

