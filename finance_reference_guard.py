"""Fail-closed task/project link guard before host writes operational state.

Invoices and GL source links are immutable history. A task may change its title,
stage or trash status, but cannot silently change the legal owning project or
disappear while financial records reference it. No files or state mutation.
"""


def ensure_finance_references_preserved(previous, proposed, finance_state):
    if not isinstance(finance_state, dict):
        raise ValueError("Financial snapshot unavailable")
    old_cards = {t['id']: t for t in previous.get('tasks', [])}
    new_cards = {t['id']: t for t in proposed.get('tasks', [])}
    new_projects = {p['id'] for p in proposed.get('projects', [])}
    binding = {}
    required_projects = set()

    def bound(card_id, project_id):
        if not isinstance(card_id, str) or not card_id or not isinstance(project_id, str):
            raise ValueError("Malformed financial source reference")
        required_projects.add(project_id)
        old = old_cards.get(card_id)
        if old is None or old.get('projectId') != project_id:
            return  # Historical orphan; don't block unrelated edits.
        known = binding.get(card_id)
        if known is not None and known != project_id:
            raise ValueError("Conflicting financial document project references")
        binding[card_id] = project_id

    for record in finance_state.get('contracts', []):
        bound(record['cardId'], record['projectId'])
    for record in finance_state.get('invoices', []):
        bound(record['cardId'], record['projectId'])
    for record in finance_state.get('ledger', []):
        if record.get('cardId') and record.get('projectId'):
            bound(record['cardId'], record['projectId'])
    for source in finance_state.get('accountingSources', {}).values():
        required_projects.add(source['projectId'])
        for card_id in source['cardIds']:
            bound(card_id, source['projectId'])
    for intake in finance_state.get('purchaseIntakes', {}).get('records', {}).values():
        required_projects.add(intake['projectId'])
        bound(intake['cardId'], intake['projectId'])

    # Historical ledger-only projects may be absent already; block only newly
    # missing projects, not unrelated edits of an existing historic fixture.
    former_projects = {p['id'] for p in previous.get('projects', [])}
    if (required_projects & former_projects) - new_projects:
        raise PermissionError("حذف پروژه دارای اسناد مالی مجاز نیست.")
    for card_id, expected_project in binding.items():
        updated = new_cards.get(card_id)
        if updated is None or updated.get('projectId') != expected_project:
            raise PermissionError("انتقال یا حذف کارت مرتبط با سند مالی مجاز نیست.")

    # An independently booked card-cost override cannot be re-parented without
    # a reviewed accounting migration even before a supplier bill is issued.
    for card_id in finance_state.get('cardCosts', {}):
        previous_card = old_cards.get(card_id)
        new_card = new_cards.get(card_id)
        if previous_card is not None and (new_card is None or
                                          previous_card.get('projectId') != new_card.get('projectId')):
            raise PermissionError("انتقال کارت دارای ثبت هزینه مالی مجاز نیست.")
    return True
