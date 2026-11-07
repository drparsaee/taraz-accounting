"""M06 server-side validation of optional task dependencies, no mutations.

This is the authoritative Python guard for JSON written by solo, LAN and restore
paths. UI graph checks are convenience only, not a permission boundary.
"""

MAX_EDGES = 200_000
MAX_PER_CARD = 128
MAX_CARDS = 20_000


def valid_dependency_id(value):
    return (isinstance(value, str) and 0 < len(value) <= 2048 and
            not any(ord(char) < 32 or ord(char) == 127 for char in value))


def validate_task_dependencies(tasks):
    if not isinstance(tasks, list) or len(tasks) > MAX_CARDS:
        raise ValueError("تعداد کارت‌های وابستگی معتبر نیست.")
    if not any(isinstance(task, dict) and "dependencies" in task for task in tasks):
        return True
    by_id = {}
    for task in tasks:
        if not isinstance(task, dict) or not valid_dependency_id(task.get("id")):
            raise ValueError("شناسه کارت برای وابستگی معتبر نیست.")
        if task["id"] in by_id:
            raise ValueError("شناسه کارت وابستگی تکراری است.")
        by_id[task["id"]] = task
    successors = {task_id: [] for task_id in by_id}
    degrees = {task_id: 0 for task_id in by_id}
    edge_count = 0
    for card in tasks:
        ids = card.get("dependencies", [])
        if not isinstance(ids, list) or len(ids) > MAX_PER_CARD:
            raise ValueError("تعداد پیش‌نیازهای کارت معتبر نیست.")
        if len(ids) != len(set(x for x in ids if isinstance(x, str))):
            raise ValueError("پیش‌نیاز تکراری است.")
        for dependency_id in ids:
            if not valid_dependency_id(dependency_id) or dependency_id == card["id"]:
                raise ValueError("شناسه پیش‌نیاز یا ارجاع به خود معتبر نیست.")
            predecessor = by_id.get(dependency_id)
            if (predecessor is None or predecessor.get("projectId") != card.get("projectId")
                    or predecessor.get("deleted") is True or card.get("deleted") is True):
                raise ValueError("پیش‌نیاز باید کارت فعال در همان پروژه باشد.")
            successors[dependency_id].append(card["id"])
            degrees[card["id"]] += 1
            edge_count += 1
            if edge_count > MAX_EDGES:
                raise ValueError("محدودیت تعداد ارتباط پیش‌نیازها رد شد.")
    queue = [task_id for task_id, degree in degrees.items() if degree == 0]
    visited = 0
    for task_id in queue:
        visited += 1
        for dependent_id in successors[task_id]:
            degrees[dependent_id] -= 1
            if degrees[dependent_id] == 0:
                queue.append(dependent_id)
    if visited != len(by_id):
        raise ValueError("CONFLICT: چرخه در پیش‌نیاز کارت‌ها وجود دارد.")
    return True
