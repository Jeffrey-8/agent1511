# results_formatter.py
"""
Модуль для форматирования результатов расчетов потенциала.
"""

from typing import Dict, List, Any


def format_calculation_results(results: Dict[str, Any]) -> str:
    """
    Форматирование результатов расчетов для вывода пользователю.
    
    Args:
        results: Результаты из calculate_potential_full_pipeline
        
    Returns:
        str: Отформатированная строка с результатами
    """
    if not results or results.get("filtered_records_count", 0) == 0:
        return "❌ Не найдено данных по заданным фильтрам."
    
    channel_results = results.get("channel_results", [])
    if not channel_results:
        return "❌ Не удалось рассчитать потенциал. Проверьте фильтры."
    
    # Группируем результаты по сегментам
    segments_data = {}
    for result in channel_results:
        seg = result["Сегмент"]
        if seg not in segments_data:
            segments_data[seg] = []
        segments_data[seg].append(result)
    
    # Формируем итоговый текст
    output = []
    output.append("📊 **Потенциал по сегментам**\n")
    
    # Считаем суммарный доход по каждому сегменту
    segment_totals = {}
    for seg, channels in segments_data.items():
        total = sum(
            r["amount_ab"] 
            for r in channels 
            if r["Решение"] == "да"
        )
        segment_totals[seg] = total
    
    # Выводим итоги по сегментам
    for seg in sorted(segment_totals.keys()):
        total = segment_totals[seg]
        if total > 0:
            output.append(f"• **{seg}**: {total:.2f} млн руб.")
        else:
            output.append(f"• **{seg}**: продажа не возможна")
    
    output.append("\n📌 **Детализация по каналам:**\n")
    
    # Выводим детализацию по каналам
    for seg in sorted(segments_data.keys()):
        output.append(f"▶ **Сегмент: {seg}**")
        
        channels = segments_data[seg]
        for channel_result in channels:
            channel = channel_result["Канал"]
            market = int(channel_result["market"])
            clients = int(channel_result["clients"])
            non_clients = int(channel_result["non_clients"])
            decision = channel_result["Решение"]
            amount_ab = channel_result["amount_ab"]
            
            if decision == "да":
                output.append(
                    f"• Канал: {channel}; "
                    f"оценка рынка = {market}, "
                    f"из них клиенты = {clients} и не клиенты = {non_clients}, "
                    f"потенциальный доход сегмента ~ {amount_ab:.2f} млн руб."
                )
            else:
                reason = channel_result.get("Причина", "неизвестная причина")
                output.append(f"• Канал: {channel}; продажа в канале не возможна ({reason})")
        
        output.append("")  # Пустая строка между сегментами
    
    return "\n".join(output)


def format_filters_summary(filters: Dict[str, Any], calculation_params: Dict[str, Any], no_filters: bool = False) -> str:
    """
    Форматирование сводки по примененным фильтрам и параметрам расчета.
    
    Args:
        filters: Словарь фильтров
        calculation_params: Параметры расчета
        no_filters: Флаг расчета без фильтров
        
    Returns:
        str: Отформатированная сводка
    """
    output = []
    
    if no_filters:
        output.append("🌐 **Режим расчета: ВЕСЬ РЫНОК (без фильтров)**\n")
        output.append("• Отрасли: весь рынок")
        output.append("• Выручка: весь рынок")
        output.append("• Штат: весь рынок")
        if filters.get("tb"):
            output.append(f"• ТБ: {', '.join(filters['tb'])}")
        else:
            output.append("• ТБ: все регионы")
    else:
        output.append("🔍 **Примененные фильтры:**\n")
        
        if filters.get("industries"):
            output.append(f"• Отрасли (ОКВЭД): {', '.join(filters['industries'])}")
        else:
            output.append("• Отрасли: не указано (весь рынок)")
        
        if filters.get("revenue"):
            output.append(f"• Выручка: {', '.join(filters['revenue'])}")
        else:
            output.append("• Выручка: не указано")
        
        if filters.get("staff"):
            output.append(f"• Штат: {', '.join(filters['staff'])}")
        else:
            output.append("• Штат: не указано")
        
        if filters.get("tb"):
            output.append(f"• ТБ: {', '.join(filters['tb'])}")
        else:
            output.append("• ТБ: не указано (все регионы)")
    
    output.append("\n⚙️ **Параметры расчета:**\n")
    output.append(f"• Средний чек ММБ: {calculation_params.get('avg_amount_mmb', 0):,.0f} руб.")
    output.append(f"• Средний чек другие сегменты: {calculation_params.get('avg_amount_other', 0):,.0f} руб.")
    output.append(f"• Кприб: {calculation_params.get('k', 0)}%")
    output.append(f"• Доля владения: {calculation_params.get('own_share', 0)}%")
    output.append(f"• Тип продукта: {calculation_params.get('product_type', 'не указано')}")
    
    return "\n".join(output)

