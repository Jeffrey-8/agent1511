# # core_agent.py
# from typing import Dict, Any
# from analytics_engine import calculate_potential_full_pipeline
#
#
# class CoreAnalyticsAgent:
#     def __init__(self, data_directory: str):
#         self.data_directory = data_directory
#
#     def run_calculation(
#         self,
#         filters: Dict[str, Any],
#         segment_params: Dict[str, Dict[str, float]],
#         product_type: str,
#     ) -> Dict[str, Any]:
#         """
#         Единственное, что делает core-агент — вызывает пайплайн расчёта.
#         Никакого LLM здесь нет.
#         """
#         result = calculate_potential_full_pipeline(
#             data_directory=self.data_directory,
#             filters=filters,
#             segment_params=segment_params,
#             product_type=product_type,
#         )
#         return result
