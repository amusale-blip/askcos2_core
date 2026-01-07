INCLUDE_OPERATIONS = [
    "run_one_step_retro_sync",
    "run_one_step_retro_async",
    "retrieve_result_by_task_id",
    "revoke_task_by_task_id"
]

OPERATION_IDS = {
    "/api/retro/call-sync": "run_one_step_retro_sync",
    "/api/retro/call-async": "run_one_step_retro_async",
    "/api/celery/task/get": "retrieve_result_by_task_id",
    "/api/celery/task/revoke": "revoke_task_by_task_id"
}
