# analytics_engine.py
"""
Модуль для расчета потенциала партнерской программы.
Адаптирован для работы с SQLite БД вместо CSV файлов.
"""
import os
import sqlite3
from typing import Optional, List, Dict, Any
import logging
import pandas as pd

from reference_data import MIN_CLIENTS, CHANNEL_COSTS, SEGMENT_CHANNELS

# Логирование
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def load_all_data_from_db(db_name: str = 'data_storage.db') -> pd.DataFrame:
    """
    Загрузка всех данных из SQLite БД.
    
    Args:
        db_name: Имя файла БД
        
    Returns:
        pd.DataFrame: DataFrame с данными из таблицы data_table
    """
    if not os.path.exists(db_name):
        logger.error(f"База данных {db_name} не найдена")
        return pd.DataFrame()
    
    try:
        conn = sqlite3.connect(db_name)
        
        # Загружаем все данные из таблицы data_table
        query = """
            SELECT 
                id_lvl_1,
                id_lvl_2,
                parameter_id,
                fact_amt,
                fact_amt_2,
                field_1_value_s,
                field_3_value_s,
                field_4_value_s,
                field_5_value_s,
                field_8_value_s,
                field_9_value_s,
                field_11_value_n,
                field_2_value_s
            FROM data_table
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        logger.info(f"✅ Загружено {len(df)} записей из БД {db_name}")
        return df
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных из БД: {e}", exc_info=True)
        return pd.DataFrame()


def filter_data(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    """
    Фильтрация по:
    - industries -> field_5_value_s (ОКВЭД)
    - revenue    -> field_8_value_s (категория выручки)
    - staff      -> field_9_value_s (категория штата)
    - tb         -> field_2_value_s (территориальный банк)
    """
    result = df.copy()

    industries = filters.get("industries") or []
    if industries:
        result = apply_okved_filter(result, industries)

    revenue = filters.get("revenue") or []
    if revenue:
        result = result[result["field_8_value_s"].isin(revenue)]

    staff = filters.get("staff") or []
    if staff:
        result = result[result["field_9_value_s"].isin(staff)]

    tb = filters.get("tb") or []
    if tb:
        result = result[result["field_2_value_s"].isin(tb)]

    logger.info(f"✅ Отфильтровано {len(result)} записей (из {len(df)} изначально)")
    return result


def apply_okved_filter(df: pd.DataFrame, industries: List[str]) -> pd.DataFrame:
    """
    Фильтр по ОКВЭД (field_5_value_s) с поддержкой "широких" кодов.

    Логика:
    - коды вида "47.0" или "47.1" трактуем как фильтр по классу "47"
      (игнорируем цифру после точки, если она 0 или 1):
        "47.0" -> класс "47" -> матчим 47.81, 47.2 и т.д.
    - все остальные коды считаем точными (полное совпадение).
    """
    industries = industries or []
    if not industries:
        return df

    result = df.copy()
    col = result["field_5_value_s"].astype(str)

    broad_classes = set()  # коды вида XX.0 или XX.1 -> класс XX
    exact_codes = set()    # остальные -> точные коды

    for code in industries:
        if not code:
            continue
        code = str(code).strip()
        parts = code.split(".")
        if len(parts) >= 2 and parts[1] in {"0", "1"}:
            # широкое условие: берём только класс (до точки)
            broad_classes.add(parts[0])
        else:
            # точное совпадение по полному коду
            exact_codes.add(code)

    # базовая маска: всё выключено
    mask = pd.Series(False, index=result.index)

    # точные совпадения, например "56.3"
    if exact_codes:
        mask = mask | col.isin(exact_codes)

    # широкие классы, например "47.0"/"47.1" -> класс "47"
    if broad_classes:
        classes = col.str.split(".", n=1).str[0]
        mask = mask | classes.isin(broad_classes)

    logger.info(
        f"[filter][okved] industries={industries} -> broad={sorted(broad_classes)} "
        f"exact={sorted(exact_codes)}; matched={mask.sum()} строк"
    )

    return result[mask]


def step_1_evaluate_market(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Шаг 1: Оценка рынка по сегментам.
    
    Для каждого сегмента рассчитывает:
    - Рынок (сумма fact_amt где field_4_value_s = "Рынок")
    - Активные клиенты Банка (сумма fact_amt где field_4_value_s = "Клиент")
    - Спящие клиенты и не клиенты (сумма fact_amt где field_4_value_s = "НеКлиент")
    - Средняя выручка, млн. р.
    - Среднее кол-во сотрудников
    """
    if df.empty:
        return {}

    df = df.copy()
    df["fact_amt"] = pd.to_numeric(df["fact_amt"], errors="coerce").fillna(0).astype(float)
    df["fact_amt_2"] = pd.to_numeric(df["fact_amt_2"], errors="coerce").fillna(0.0).astype(float)
    df["field_11_value_n"] = pd.to_numeric(df["field_11_value_n"], errors="coerce").fillna(0.0).astype(float)

    result: Dict[str, Dict[str, Any]] = {}

    for seg, df_seg in df.groupby("field_1_value_s"):

        # a. Рынок
        df_market = df_seg[df_seg["field_4_value_s"] == "Рынок"]

        # b. Клиенты
        df_clients = df_seg[df_seg["field_4_value_s"] == "Клиент"]

        # c. Не клиенты
        df_non_clients = df_seg[df_seg["field_4_value_s"] == "НеКлиент"]

        # Рассчитываем суммы из данных
        market_sum_from_data = float(df_market["fact_amt"].sum())
        client_sum = float(df_clients["fact_amt"].sum())
        non_client_sum = float(df_non_clients["fact_amt"].sum())

        # ✅ Согласно ТЗ: Рынок = Клиент + НеКлиент
        market_sum = client_sum + non_client_sum
        
        # Проверка расхождения с данными
        diff = market_sum_from_data - market_sum
        if abs(diff) > 0.01:
            logger.warning(
                f"[CHECK STEP1] SEG={seg} | РАСХОЖДЕНИЕ: market_from_data={market_sum_from_data:.2f} | "
                f"market_calculated={market_sum:.2f} | clients={client_sum:.2f} | "
                f"non_clients={non_client_sum:.2f} | diff={diff:.2f}"
            )
        else:
            logger.info(
                f"[CHECK STEP1] SEG={seg} | market={market_sum:.2f} | "
                f"clients={client_sum:.2f} | non_clients={non_client_sum:.2f} | OK"
            )

        # d. Средняя выручка, млн. р.
        num_revenue = float(df_market["fact_amt_2"].sum())

        denom_revenue = float(df_market["fact_amt"].sum()) + float(
            df_seg[df_seg["field_4_value_s"] != "Рынок"].shape[0]
        )

        if denom_revenue > 0:
            avg_revenue_mln = round(num_revenue / denom_revenue, 3)
        else:
            avg_revenue_mln = 0.0

        # e. Среднее кол-во сотрудников
        num_staff = float(df_market["field_11_value_n"].sum())
        denom_staff = denom_revenue

        if denom_staff > 0:
            avg_staff = int(round(num_staff / denom_staff))
        else:
            avg_staff = 0

        result[seg] = {
            "Рынок": market_sum,
            "Активные клиенты Банка": client_sum,
            "Спящие клиенты и не клиенты Банка": non_client_sum,
            "Средняя выручка, млн. р.": avg_revenue_mln,
            "Среднее кол-во сотрудников": avg_staff,
        }

    return result


def step_2_calculate_potential(
    segment_metrics: Dict[str, Dict[str, Any]],
    avg_amount_mmb: float,
    avg_amount_other: float,
    k: float,
    own_share: float,
    product_type: str,
) -> List[Dict[str, Any]]:
    """
    Шаг 2: Расчёт потенциала.

    Для каждого сегмента:
      1. calc_clients = "Рынок"
      2. проверка минимального количества клиентов для канала
      3. для оставшихся каналов:
         - potential_amount (млн руб.)
         - rate_ab (%)
         - amount_ab (млн руб.)
         - решение "да/нет"
    """

    results: List[Dict[str, Any]] = []
    utilization = 0.05  # 5%

    for seg, metrics in segment_metrics.items():
        market_sum = float(metrics.get("Рынок", 0.0))
        clients_sum = float(metrics.get("Активные клиенты Банка", 0.0))
        non_clients_sum = float(metrics.get("Спящие клиенты и не клиенты Банка", 0.0))

        calc_clients = market_sum  # строго по ТЗ

        channels = SEGMENT_CHANNELS.get(seg, [])
        if not channels:
            continue

        if seg == "ММБ":
            avg_amount_for_seg = avg_amount_mmb
        else:
            avg_amount_for_seg = avg_amount_other

        for channel in channels:
            min_clients = MIN_CLIENTS.get((channel, seg))
            if min_clients is None:
                results.append(
                    {
                        "Сегмент": seg,
                        "Канал": channel,
                        "calc_clients": calc_clients,
                        "market": market_sum,
                        "clients": clients_sum,
                        "non_clients": non_clients_sum,
                        "potential_amount": 0.0,
                        "rate_ab": 0.0,
                        "amount_ab": 0.0,
                        "Решение": "нет",
                        "Причина": "нет данных по минимальному количеству клиентов",
                    }
                )
                continue

            # 2. проверка calc_clients vs min_clients
            if calc_clients < min_clients:
                results.append(
                    {
                        "Сегмент": seg,
                        "Канал": channel,
                        "calc_clients": calc_clients,
                        "market": market_sum,
                        "clients": clients_sum,
                        "non_clients": non_clients_sum,
                        "potential_amount": 0.0,
                        "rate_ab": 0.0,
                        "amount_ab": 0.0,
                        "Решение": "нет",
                        "Причина": "calc_clients < min_clients",
                    }
                )
                continue

            if avg_amount_for_seg <= 0:
                results.append(
                    {
                        "Сегмент": seg,
                        "Канал": channel,
                        "calc_clients": calc_clients,
                        "market": market_sum,
                        "clients": clients_sum,
                        "non_clients": non_clients_sum,
                        "potential_amount": 0.0,
                        "rate_ab": 0.0,
                        "amount_ab": 0.0,
                        "Решение": "нет",
                        "Причина": "средний чек = 0",
                    }
                )
                continue

            cost_price = CHANNEL_COSTS.get((channel, seg, product_type))
            if cost_price is None:
                results.append(
                    {
                        "Сегмент": seg,
                        "Канал": channel,
                        "calc_clients": calc_clients,
                        "market": market_sum,
                        "clients": clients_sum,
                        "non_clients": non_clients_sum,
                        "potential_amount": 0.0,
                        "rate_ab": 0.0,
                        "amount_ab": 0.0,
                        "Решение": "нет",
                        "Причина": "нет данных по себестоимости",
                    }
                )
                continue

            # 3.a potential_amount
            potential_amount = calc_clients * avg_amount_for_seg / 1_000_000 * utilization
            potential_amount = round(potential_amount, 1)

            # 3.b rate_ab
            rate_ab = cost_price / avg_amount_for_seg * 100.0
            rate_ab = round(rate_ab, 1)

            if rate_ab == 0.0:
                results.append(
                    {
                        "Сегмент": seg,
                        "Канал": channel,
                        "calc_clients": calc_clients,
                        "market": market_sum,
                        "clients": clients_sum,
                        "non_clients": non_clients_sum,
                        "potential_amount": potential_amount,
                        "rate_ab": rate_ab,
                        "amount_ab": 0.0,
                        "Решение": "нет",
                        "Причина": "ставка после округления = 0%",
                    }
                )
                continue

            # 3.c amount_ab
            amount_ab = potential_amount * (k / 100.0 + rate_ab / 100.0)
            amount_ab = round(amount_ab, 3)

            results.append(
                {
                    "Сегмент": seg,
                    "Канал": channel,
                    "calc_clients": calc_clients,
                    "market": market_sum,
                    "clients": clients_sum,
                    "non_clients": non_clients_sum,
                    "potential_amount": potential_amount,
                    "rate_ab": rate_ab,
                    "amount_ab": amount_ab,
                    "Решение": "да",
                    "Причина": "",
                }
            )

    return results


def calculate_potential_full_pipeline(
    db_name: str,
    filters: Dict[str, Any],
    avg_amount_mmb: float,
    avg_amount_other: float,
    k: float,
    own_share: float,
    product_type: str,
) -> Dict[str, Any]:
    """
    Полный пайплайн расчета потенциала для телеграм-бота.
    
    Args:
        db_name: Имя файла БД
        filters: Словарь фильтров (industries, revenue, staff, tb)
        avg_amount_mmb: Средний чек в ММБ, руб.
        avg_amount_other: Средний чек в других сегментах, руб.
        k: Кприб, %
        own_share: Доля владения, %
        product_type: Тип продукта ("Коробка" или "Кастом")
        
    Returns:
        Dict с результатами расчетов
    """
    all_data = load_all_data_from_db(db_name)
    if all_data.empty:
        logger.warning("Нет данных в БД для расчетов")
        return {
            "filtered_records_count": 0,
            "segment_metrics": {},
            "channel_results": [],
        }
    
    filtered = filter_data(all_data, filters)
    segment_metrics = step_1_evaluate_market(filtered)
    channel_results = step_2_calculate_potential(
        segment_metrics=segment_metrics,
        avg_amount_mmb=avg_amount_mmb,
        avg_amount_other=avg_amount_other,
        k=k,
        own_share=own_share,
        product_type=product_type,
    )
    return {
        "filtered_records_count": len(filtered),
        "segment_metrics": segment_metrics,
        "channel_results": channel_results,
    }

