"""Fail-closed project identity rules for ordinary task-state saves.

Cross-project migration needs a single transaction for collaboration history,
permissions and financial associations. Until that protocol exists, normal
saves must not silently reparent existing cards or orphan project records.
Offline full recovery uses a separate, explicitly scoped restore protocol.
"""


def ensure_project_identity_preserved(previous, candidate, *, accounts=None,
                                      collaboration=None):
    before = {item["id"]: item for item in previous["tasks"]}
    for item in candidate["tasks"]:
        old = before.get(item["id"])
        if old and old["projectId"] != item["projectId"]:
            raise PermissionError(
                "انتقال کارت میان پروژه‌ها تا آماده‌شدن انتقال اتمیک تاریخچه، "
                "دسترسی‌ها و اسناد مالی مجاز نیست.")

    old_projects = {item["id"] for item in previous["projects"]}
    new_projects = {item["id"] for item in candidate["projects"]}
    removed = old_projects - new_projects
    if not removed:
        return

    # Deleting even an empty project can invalidate a different LAN user's
    # scoped grant. Never rewrite those grants implicitly.
    if isinstance(accounts, dict):
        users = accounts.values()
    elif isinstance(accounts, list):
        users = accounts
    else:
        users = ()
    for user in users:
        grants = user.get("projects")
        if isinstance(grants, list) and removed.intersection(grants):
            raise PermissionError(
                "پروژه دارای دسترسی فعال کاربر شبکه است؛ حذف بدون اصلاح صریح دسترسی‌ها مجاز نیست.")

    # A project without cards may still own durable automation rules and
    # historical collaboration records. Those are data, not disposable UI.
    if isinstance(collaboration, dict):
        for category in ("comments", "activity", "notifications", "rules"):
            for item in collaboration.get(category, []):
                if item.get("projectId") in removed:
                    raise ValueError(
                        "پروژه دارای تاریخچه همکاری یا قانون ثبت‌شده است؛ حذف مجاز نیست.")


def ensure_partial_restore_safe(previous, candidate, *, collaboration,
                                finance, accounts=None):
    """Reject task-only snapshots that would orphan or misattribute side data.

    These checks are ONLY for task/board JSON or Drive recovery. A verified
    full-domain offline restore must be allowed to replace the domains together.
    """
    from finance_reference_guard import ensure_finance_references_preserved

    ensure_project_identity_preserved(previous, candidate, accounts=accounts,
                                      collaboration=collaboration)
    ensure_finance_references_preserved(previous, candidate, finance)
    before = {card["id"]: card for card in previous["tasks"]}
    after = {card["id"]: card for card in candidate["tasks"]}

    def verify_bound_card(card_id):
        if not card_id or (card_id not in before and card_id not in after):
            return
        older = before.get(card_id)
        newer = after.get(card_id)
        if older is None or newer is None or older["projectId"] != newer["projectId"]:
            raise PermissionError(
                "این پشتیبان تنها داده کارت‌ها را دارد و با تاریخچه همکاری سازگار نیست؛ "
                "برای بازیابی کامل، پشتیبان چنددامنه‌ای آفلاین لازم است.")
        if (older.get("createdAt") and newer.get("createdAt") and
                older["createdAt"] != newer["createdAt"]):
            raise PermissionError(
                "شناسه کارت بازیابی‌شده با تاریخچه موجود تناقض دارد؛ بازیابی متوقف شد.")

    for group in ("comments", "activity", "notifications"):
        for item in collaboration.get(group, []):
            verify_bound_card(item.get("cardId"))
    for card_id, watchers in collaboration.get("watchers", {}).items():
        if watchers:
            verify_bound_card(card_id)

    # A previously orphaned financial source must not silently be assigned to
    # a *different* card resurrected from an old tasks-only snapshot.
    bound_finance_cards = {item["cardId"] for key in ("contracts", "invoices")
                           for item in finance.get(key, []) if item.get("cardId")}
    bound_finance_cards.update(item["cardId"] for item in finance.get("ledger", [])
                               if item.get("cardId"))
    bound_finance_cards.update(card_id for item in finance.get("accountingSources", {}).values()
                               for card_id in item.get("cardIds", []))
    bound_finance_cards.update(item["cardId"] for item in
                               finance.get("purchaseIntakes", {}).get("records", {}).values()
                               if item.get("cardId"))
    bound_finance_cards.update(finance.get("cardCosts", {}))
    if any(card_id in after and card_id not in before for card_id in bound_finance_cards):
        raise PermissionError("بازیابی شناسه کارت مرتبط با سند مالی قدیمی مجاز نیست.")
