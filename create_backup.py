# -*- coding: utf-8 -*-
"""
Скрипт для создания архива проекта со всеми файлами, включая базы данных.
"""
import os
import zipfile
import shutil
from datetime import datetime
import sys
import io

# Устанавливаем кодировку для вывода
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def create_backup():
    """Создание архива проекта."""
    # Получаем текущую директорию
    project_dir = os.getcwd()
    
    # Имя архива с датой и временем
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    archive_name = f"agent1511_backup_{date_str}.zip"
    
    # Файлы и папки для исключения
    exclude_patterns = [
        '.git',
        '__pycache__',
        '*.pyc',
        '*.pyo',
        '*.zip',
        'agent1511_backup_*.zip',
        '.env'  # Исключаем .env для безопасности (можно раскомментировать, если нужен)
    ]
    
    print(f"Создание архива: {archive_name}")
    print(f"Директория проекта: {project_dir}")
    print()
    
    # Список файлов для архивации
    files_to_archive = []
    skipped_files = []
    
    for root, dirs, files in os.walk(project_dir):
        # Исключаем .git и __pycache__
        dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__']]
        
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, project_dir)
            
            # Пропускаем сам архив и другие исключения
            if any(rel_path.startswith(exc.replace('*', '')) or rel_path.endswith(exc.replace('*', '')) 
                   for exc in exclude_patterns if '*' in exc):
                continue
            if any(exc in rel_path for exc in exclude_patterns if '*' not in exc):
                continue
            
            # Пропускаем сам создаваемый архив
            if file == archive_name:
                continue
            
            files_to_archive.append((file_path, rel_path))
    
    # Создаем архив
    total_size = 0
    archived_count = 0
    
    try:
        with zipfile.ZipFile(archive_name, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            for file_path, rel_path in files_to_archive:
                try:
                    # Пытаемся добавить файл
                    zipf.write(file_path, rel_path)
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    archived_count += 1
                    print(f"  [+] {rel_path} ({file_size / 1024 / 1024:.2f} MB)")
                except PermissionError as e:
                    skipped_files.append((rel_path, f"Permission denied: {e}"))
                    print(f"  [!] Пропущен (заблокирован): {rel_path}")
                except Exception as e:
                    skipped_files.append((rel_path, f"Error: {e}"))
                    print(f"  [!] Ошибка: {rel_path} - {e}")
        
        archive_size = os.path.getsize(archive_name)
        
        print()
        print("=" * 60)
        print(f"Архив создан: {archive_name}")
        print(f"Размер архива: {archive_size / 1024 / 1024:.2f} MB")
        print(f"Исходный размер: {total_size / 1024 / 1024:.2f} MB")
        print(f"Сжатие: {(1 - archive_size / total_size) * 100:.1f}%")
        print(f"Файлов в архиве: {archived_count}")
        
        if skipped_files:
            print()
            print(f"Пропущено файлов: {len(skipped_files)}")
            for file_path, reason in skipped_files:
                print(f"  - {file_path}: {reason}")
            print()
            print("ВНИМАНИЕ: Некоторые файлы не были добавлены в архив!")
            print("Убедитесь, что все процессы, использующие эти файлы, закрыты.")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"Ошибка при создании архива: {e}")
        if os.path.exists(archive_name):
            os.remove(archive_name)
        return False
    
    return True

if __name__ == "__main__":
    try:
        create_backup()
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(1)

