INCLUDE_OPERATIONS = [
    "askcos_run_retro_expansion_async",
    "askcos_run_forward_async",
    "askcos_run_conditions_async",
    "askcos_retrieve_async_result_by_task_id",
    "askcos_check_templates",
    "askcos_draw_util",
    "askcos_login",
    "askcos_logout"
]

OPERATION_IDS = {
    ("/api/retro/controller/call-sync", "POST"): "askcos_run_one_step_retro_sync",
    ("/api/retro/controller/call-async", "POST"): "askcos_run_one_step_retro_async",
    ("/api/tree-search/expand-one/call-sync", "POST"): "askcos_run_retro_expansion_sync",
    ("/api/tree-search/expand-one/call-async", "POST"): "askcos_run_retro_expansion_async",
    ("/api/forward/controller/call-sync", "POST"): "askcos_run_forward_sync",
    ("/api/forward/controller/call-async", "POST"): "askcos_run_forward_async",
    ("/api/context/quarc/call-sync", "POST"): "askcos_run_conditions_sync",
    ("/api/context/quarc/call-async", "POST"): "askcos_run_conditions_async",
    ("/api/template/lookup", "POST"): "askcos_check_templates",
    ("/api/celery/task/get", "GET"): "askcos_retrieve_async_result_by_task_id",
    ("/api/celery/task/revoke", "GET"): "askcos_revoke_task_by_task_id",
    ("/api/draw", "POST"): "askcos_draw_util",
    ("/api/admin/mcp-login", "POST"): "askcos_login",
    ("/api/admin/logout", "POST"): "askcos_logout"
}
