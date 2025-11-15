# analytics_engine.py
import os
import glob
from dataclasses import dataclass
from typing import Optional, List, Dict
import logging

from reference_data import (
    MIN_CLIENTS_CONFIG,
    COST_PRICE_CONFIG,
    SEGMENT_DOLYA_DEFAULT,
    SEGMENT_KPRIB_DEFAULT,
)

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


def load_all_data(directory: str) -> List[FileData]:
    """
    Загрузка всех CSV файлов формата output_excel_part_*.csv из директории.
    """
    normalized_dir = os.path.normpath(directory)
    if not os.path.isabs(normalized_dir):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        normalized_dir = os.path.join(script_dir, normalized_dir)

    pattern = os.path.join(normalized_dir, "output_excel_part_*.csv")
    files = sorted(glob.glob(pattern))

    if not files:
        logger.error(f"❌ Не найдено CSV файлов в директории: {normalized_dir}")
        logger.error(f"🔍 Искал по паттерну: {pattern}")
        return []

    logger.info(f"📁 Найдено {len(files)} CSV файлов в {normalized_dir}")
    data: List[FileData] = []
    for file in files:
        logger.info(f"📄 Читаю {os.path.basename(file)}...")
        with open(file, "r", encoding="utf-8") as f:
            _ = f.readline()  # пропускаем шапку
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = FileData.from_csv_row(line)
                    data.append(record)
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка обработки строки: {e}")
    logger.info(f"✅ Загружено {len(data)} записей")
    return data


def filter_data(data: List[FileData], filters: Dict) -> List[FileData]:
    """
    Фильтрация данных согласно аналитике:
    1. industries -> field_5_value_s (ОКВЭД)
    2. revenue    -> field_8_value_s
    3. staff      -> field_9_value_s
    4. tb         -> field_2_value_s
    """
    logger.info("🔍 Применяю фильтры к данным...")
    result: List[FileData] = []

    for record in data:
        # 1. Отрасли (ОКВЭД)
        industries = filters.get("industries")
        if industries:
            if not record.field_5_value_s or record.field_5_value_s not in industries:
                continue

        # 2. Выручка
        revenue = filters.get("revenue")
        if revenue:
            if not record.field_8_value_s or record.field_8_value_s not in revenue:
                continue

        # 3. Штат
        staff = filters.get("staff")
        if staff:
            if not record.field_9_value_s or record.field_9_value_s not in staff:
                continue

        # 4. ТБ
        tb = filters.get("tb")
        if tb:
            if not record.field_2_value_s or record.field_2_value_s not in tb:
                continue

        result.append(record)

    logger.info(f"✅ Отфильтровано {len(result)} записей (из {len(data)})")
    return result


def step_1_evaluate_market(data: List[FileData]) -> Dict[str, Dict]:
    """
    Шаг 1: Оценка рынка по сегментам (field_1_value_s) согласно аналитике.
    На выходе по каждому сегменту:
      - 'Рынок' / 'Активные клиенты Банка' / 'Спящие клиенты и не клиенты Банка'
        (суммы fact_amt)
      - 'Средняя выручка, млн. р.' (по формуле аналитики)
      - 'Среднее кол-во сотрудников'
      - 'avg_check' (средний чек в руб.)
    """
    logger.info("📊 Выполняю шаг 1: оценка рынка по сегментам...")
    segments: Dict[str, Dict] = {}

    for record in data:
        seg = record.field_1_value_s or "Неизвестно"
        if seg not in segments:
            segments[seg] = {
                "Рынок": 0.0,
                "Активные клиенты Банка": 0.0,
                "Спящие клиенты и не клиенты Банка": 0.0,
                "num_non_market": 0,          # количество строк, где field_4_value_s <> "Рынок"
                "fact_amt_2_sum_rynek": 0.0,  # сумма fact_amt_2 по "Рынок"
                "fact_amt_sum_rynek": 0.0,    # сумма fact_amt по "Рынок"
                "field_11_sum_rynek": 0.0,    # сумма сотрудников по "Рынок"
                "Средняя выручка, млн. р.": 0.0,
                "Среднее кол-во сотрудников": 0,
                "avg_check": 0.0,             # средний чек (руб.)
            }

        field_4 = record.field_4_value_s
        fact_amt = record.fact_amt or 0.0
        fact_amt_2 = record.fact_amt_2 or 0.0
        field_11 = record.field_11_value_n or 0

        # a. Рынок: суммируем fact_amt и fact_amt_2, сотрудников
        if field_4 == "Рынок":
            segments[seg]["Рынок"] += fact_amt
            segments[seg]["fact_amt_2_sum_rynek"] += fact_amt_2
            segments[seg]["fact_amt_sum_rynek"] += fact_amt
            segments[seg]["field_11_sum_rynek"] += field_11

        # b. Активные клиенты Банка
        elif field_4 == "Клиент":
            segments[seg]["Активные клиенты Банка"] += fact_amt

        # c. Спящие клиенты и не клиенты Банка
        elif field_4 == "НеКлиент":
            segments[seg]["Спящие клиенты и не клиенты Банка"] += fact_amt

        # d. num_non_market — количество строк не "Рынок"
        if field_4 != "Рынок":
            segments[seg]["num_non_market"] += 1

    # Расчёт средних величин
    for seg, vals in segments.items():
        denominator = vals["fact_amt_sum_rynek"] + vals["num_non_market"]

        if denominator > 0:
            # Средняя выручка, млн. р. (как в аналитике)
            avg_revenue = vals["fact_amt_2_sum_rynek"] / denominator / 1_000_000
            vals["Средняя выручка, млн. р."] = round(avg_revenue, 3)

            # Среднее количество сотрудников
            avg_staff = vals["field_11_sum_rynek"] / denominator
            vals["Среднее кол-во сотрудников"] = int(round(avg_staff))
        else:
            vals["Средняя выручка, млн. р."] = 0.0
            vals["Среднее кол-во сотрудников"] = 0

        # Средний чек (руб/клиент) = sum(fact_amt_2 по рынку) / sum(fact_amt по рынку)
        if vals["fact_amt_sum_rynek"] > 0:
            avg_check = vals["fact_amt_2_sum_rynek"] / vals["fact_amt_sum_rynek"]
            vals["avg_check"] = avg_check
        else:
            # Если нет данных по рынку — ставим некий дефолт
            vals["avg_check"] = 100_000.0

        logger.info(
            f"Сегмент {seg}: Рынок={vals['Рынок']:.0f}, Клиенты={vals['Активные клиенты Банка']:.0f}, "
            f"НеКлиенты={vals['Спящие клиенты и не клиенты Банка']:.0f}, "
            f"avg_check={vals['avg_check']:.2f}"
        )

    logger.info(f"✅ Шаг 1 завершён: рассчитано {len(segments)} сегментов")
    return segments


def _get_cost_price(channel: str, segment: str, product_type: str) -> float:
    """
    Получить себестоимость из справочника по Каналу, Сегменту и Типу продукта.
    Если не найдено — вернуть условный дефолт 1000.0.
    """
    for cp in COST_PRICE_CONFIG:
        if (
            cp["Канал"] == channel
            and cp["Тип продукта"] == product_type
            and cp["Тип суммы"] == "Себестоимость"
            and cp["Сегмент"] == segment
        ):
            return cp["Сумма"]
    logger.warning(
        f"⚠️ Не найдена себестоимость для Канал={channel}, Сегмент={segment}, Тип продукта={product_type}. "
        f"Использую дефолт 1000.0"
    )
    return 1000.0


def step_2_calculate_potential(
    segment_metrics: Dict[str, Dict],
    segment_params: Dict[str, Dict[str, float]],
    product_type: str = "Коробка",
) -> List[Dict]:
    """
    Шаг 2: расчёт потенциала по каждому сегменту и каналу.

    segment_params: словарь вида:
        {
          "ММБ": {"dolya": 6.0, "kpr": 15.0},
          "КСБ": {"dolya": 10.0, "kpr": 20.0},
          ...
        }

    Если для сегмента нет параметров — берём из SEGMENT_DOLYA_DEFAULT / SEGMENT_KPRIB_DEFAULT.
    """
    logger.info(f"🧮 Выполняю шаг 2: расчет потенциала, Тип продукта={product_type}")
    results: List[Dict] = []
    utilization_rate = 0.05  # 5% по аналитике

    for seg, metrics in segment_metrics.items():
        # 1. calc_clients = сумма ("Рынок" + "Активные клиенты" + "Спящие клиенты и не клиенты банка")
        calc_clients = (
            (metrics.get("Рынок") or 0.0)
            + (metrics.get("Активные клиенты Банка") or 0.0)
            + (metrics.get("Спящие клиенты и не клиенты Банка") or 0.0)
        )

        avg_check = metrics.get("avg_check") or 100_000.0

        # Каналы, которые работают с этим сегментом
        channels = [c for c in MIN_CLIENTS_CONFIG if c["Сегмент"] == seg]
        if not channels:
            logger.info(f"ℹ️ Для сегмента {seg} нет каналов в справочнике MIN_CLIENTS_CONFIG")
            continue

        for channel_info in channels:
            channel = channel_info["Канал"]
            min_clients = channel_info["Минимальное кол-во клиентов"]

            logger.info(
                f"Сегмент {seg}, Канал {channel}: calc_clients={calc_clients:.3f}, "
                f"min_clients={min_clients}"
            )

            # 2. Если calc_clients < min_clients → продажа в канале = "нет"
            if calc_clients < min_clients:
                results.append(
                    {
                        "Канал": channel,
                        "Сегмент": seg,
                        "calc_clients": round(calc_clients, 3),
                        "potential_amount": 0.0,
                        "rate_ab": 0.0,
                        "amount_ab": 0.0,
                        "amount_chkd": 0.0,
                        "revenue": 0.0,
                        "total_potential": 0.0,
                        "Решение": "нет",
                        "Пояснение": "Мало клиентов (calc_clients < min_clients)",
                    }
                )
                continue

            # 3.a себестоимость канала с учётом типа продукта и сегмента
            cost_price = _get_cost_price(channel, seg, product_type)

            # 3.a.ii Расчёт потенциала: calc_clients * средний чек / 1 000 000 * 0.05
            potential_amount = calc_clients * avg_check / 1_000_000 * utilization_rate
            potential_amount = round(potential_amount, 3)

            # 3.b.ii Ставка rate_ab = cost_price / средний чек * 100
            rate_ab = round(cost_price / avg_check * 100, 1)

            # 3.b.iv Если после округления ставка 0 — продажа невозможна
            if rate_ab == 0.0:
                results.append(
                    {
                        "Канал": channel,
                        "Сегмент": seg,
                        "calc_clients": round(calc_clients, 3),
                        "potential_amount": potential_amount,
                        "rate_ab": rate_ab,
                        "amount_ab": 0.0,
                        "amount_chkd": 0.0,
                        "revenue": 0.0,
                        "total_potential": 0.0,
                        "Решение": "нет",
                        "Пояснение": "Ставка 0% после округления",
                    }
                )
                continue

            # 3.c amount_ab = potential_amount * rate_ab / 100
            amount_ab = potential_amount * rate_ab / 100.0

            # 3.d, 3.e: Доля владения и Кприб
            seg_dolya = segment_params.get(seg, {}).get("dolya")
            seg_kprib = segment_params.get(seg, {}).get("kpr")

            if seg_dolya is None:
                seg_dolya = SEGMENT_DOLYA_DEFAULT.get(seg, 0.0)
                logger.warning(f"⚠️ Не задана доля владения для сегмента {seg}, использую дефолт {seg_dolya}")
            if seg_kprib is None:
                seg_kprib = SEGMENT_KPRIB_DEFAULT.get(seg, 0.0)
                logger.warning(f"⚠️ Не задан Кприб для сегмента {seg}, использую дефолт {seg_kprib}")

            amount_chkd = amount_ab * seg_dolya / 100.0
            revenue_val = amount_chkd * seg_kprib / 100.0

            # 3.f Итоговый потенциал для канала: amount_ab + amount_chkd + revenue
            total_potential = amount_ab + amount_chkd + revenue_val

            result_row = {
                "Канал": channel,
                "Сегмент": seg,
                "calc_clients": round(calc_clients, 3),
                "potential_amount": potential_amount,
                "rate_ab": rate_ab,
                "amount_ab": round(amount_ab, 3),
                "amount_chkd": round(amount_chkd, 3),
                "revenue": round(revenue_val, 3),
                "total_potential": round(total_potential, 3),
                "Решение": "да",
                "Пояснение": "Прошёл все проверки",
            }
            results.append(result_row)
            logger.info(
                f"✓ {seg} / {channel}: potential_amount={potential_amount}, rate_ab={rate_ab}, "
                f"total_potential={result_row['total_potential']}"
            )

    logger.info(f"✅ Шаг 2 завершён: рассчитано {len(results)} записей по каналам")
    return results


def calculate_potential_full_pipeline(
    data_directory: str,
    filters: Dict,
    segment_params: Dict[str, Dict[str, float]],
    product_type: str = "Коробка",
) -> Dict:
    """
    Полный пайплайн:
      1. Загрузка данных
      2. Фильтрация по industries / revenue / staff / tb
      3. Шаг 1: оценка рынка
      4. Шаг 2: расчёт потенциала
    """
    logger.info("🚀 Запуск полного пайплайна расчёта потенциала")

    all_data = load_all_data(data_directory)
    filtered_data = filter_data(all_data, filters)
    segment_metrics = step_1_evaluate_market(filtered_data)
    potential_results = step_2_calculate_potential(segment_metrics, segment_params, product_type)

    pipeline_result = {
        "segment_metrics": segment_metrics,
        "potential_results": potential_results,
        "filtered_records_count": len(filtered_data),
    }

    logger.info("🏁 Пайплайн расчёта потенциала завершён")
    return pipeline_result
