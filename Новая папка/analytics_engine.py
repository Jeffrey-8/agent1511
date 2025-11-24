# analytics_engine.py
import os
import glob
from dataclasses import dataclass
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


@dataclass
class FileData:
    id_lvl_1: Optional[int] = None
    id_lvl_2: Optional[int] = None
    parameter_id: Optional[str] = None
    fact_amt: Optional[float] = None
    fact_amt_2: Optional[float] = None
    field_1_value_s: Optional[str] = None  # сегмент
    field_3_value_s: Optional[str] = None
    field_4_value_s: Optional[str] = None  # "Рынок", "Клиент", "НеКлиент"
    field_5_value_s: Optional[str] = None  # отрасль (ОКВЭД)
    field_8_value_s: Optional[str] = None  # выручка категория
    field_9_value_s: Optional[str] = None  # штат категория
    field_11_value_n: Optional[int] = None  # кол-во сотрудников
    field_2_value_s: Optional[str] = None  # ТБ

    @staticmethod
    def _normalize_str(value: Optional[str]) -> str:
        return (value or "").strip()

    @staticmethod
    def parse_int(value: str) -> Optional[int]:
        value = value.strip().replace(',', '.')
        if not value or value.lower() in ('', 'null', 'none'):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def parse_float(value: str) -> Optional[float]:
        value = value.strip().replace(',', '.')
        if not value or value.lower() in ('', 'null', 'none'):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @classmethod
    def from_csv_row(cls, row: str) -> "FileData":
        # простой CSV по запятой без кавычек
        fields = row.strip().split(',')
        if len(fields) < 21:
            fields += [''] * (21 - len(fields))

        return cls(
            id_lvl_1=cls.parse_int(fields[0]),
            id_lvl_2=cls.parse_int(fields[1]),
            parameter_id=cls._normalize_str(fields[2]) or None,
            fact_amt=cls.parse_float(fields[3]),
            fact_amt_2=cls.parse_float(fields[4]),
            field_1_value_s=cls._normalize_str(fields[5]) or None,
            field_3_value_s=cls._normalize_str(fields[6]) or None,
            field_4_value_s=cls._normalize_str(fields[7]) or None,
            field_5_value_s=cls._normalize_str(fields[8]) or None,
            field_8_value_s=cls._normalize_str(fields[11]) or None,
            field_9_value_s=cls._normalize_str(fields[12]) or None,
            field_11_value_n=cls.parse_int(fields[14]),
            field_2_value_s=cls._normalize_str(fields[19]) or None,
        )


def load_all_data(data_dir: str) -> pd.DataFrame:
    import os
    import pandas as pd
    import logging

    logger = logging.getLogger(__name__)

    all_files = [f for f in os.listdir(data_dir) if f.endswith(".csv")]
    logger.info(f"📁 Найдено {len(all_files)} CSV файлов в {data_dir}")

    dfs = []
    for file in all_files:
        path = os.path.join(data_dir, file)
        logger.info(f"📄 Читаю {file}...")

        df = pd.read_csv(
            path,
            sep=",",
            engine="python",
            encoding="utf-8",
            on_bad_lines="skip",
        )

        dfs.append(df)

    if not dfs:
        logger.warning("⚠ Нет данных после чтения CSV")
        return pd.DataFrame()

    full_df = pd.concat(dfs, ignore_index=True)
    logger.info(f"✅ Загружено {len(full_df)} записей")

    return full_df

def filter_data(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    """
    Фильтрация по:
    - industries -> field_5_value_s
    - revenue    -> field_8_value_s
    - staff      -> field_9_value_s
    - tb         -> field_2_value_s
    """
    result = df

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


def step_1_evaluate_market(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
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

        market_sum = float(df_market["fact_amt"].sum())
        client_sum = float(df_clients["fact_amt"].sum())
        non_client_sum = float(df_non_clients["fact_amt"].sum())

        # ✅ мини-проверка
        diff = market_sum - (client_sum + non_client_sum)
        logger.info(
            f"[CHECK STEP1] SEG={seg} | market={market_sum} | "
            f"clients={client_sum} | non_clients={non_client_sum} | diff={diff}"
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



#
# def _get_cost_price(channel: str, segment: str, product_type: str) -> float:
#     """
#     Получить себестоимость из справочника по Каналу, Сегменту и Типу продукта.
#     Если не найдено — вернуть условный дефолт 1000.0.
#     """
#     for cp in COST_PRICE_CONFIG:
#         if (
#             cp["Канал"] == channel
#             and cp["Тип продукта"] == product_type
#             and cp["Тип суммы"] == "Себестоимость"
#             and cp["Сегмент"] == segment
#         ):
#             return cp["Сумма"]
#     logger.warning(
#         f"⚠️ Не найдена себестоимость для Канал={channel}, Сегмент={segment}, Тип продукта={product_type}. "
#         f"Использую дефолт 1000.0"
#     )
#     return 1000.0


def step_2_calculate_potential(
    segment_metrics: Dict[str, Dict[str, Any]],
    avg_amount_mmb: float,
    avg_amount_other: float,
    k: float,
    own_share: float,
    product_type: str,
) -> List[Dict[str, Any]]:
    """
    Шаг 2 по новой аналитике.

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
    data_dir: str,
    filters: Dict[str, Any],
    avg_amount_mmb: float,
    avg_amount_other: float,
    k: float,
    own_share: float,
    product_type: str,
) -> Dict[str, Any]:
    """
    Новый пайплайн по аналитике для микроприложения.
    """
    all_data = load_all_data(data_dir)
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

def apply_okved_filter(df: pd.DataFrame, industries) -> pd.DataFrame:
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

    result = df
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
