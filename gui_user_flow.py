"""Interactive QA for the standalone accounting route and disposable task store.

Run only from the owned EXE smoke runner with a synthetic AppData profile.
Financial operations are read-only. The sole mutation creates one QA task.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import time


TASK_TITLE = 'آزمون رابط تست کاربر مدار QA'


def _require_isolated_qa(bridge):
    """Reject accidental execution on a user desktop or LAN-connected host."""
    env = os.environ
    if any(env.get(flag) != '1' for flag in ('MADAR_RELEASE_QA', 'MADAR_QA_INTERACTION')):
        raise RuntimeError('interactive GUI QA must be explicitly enabled')
    if env.get('MADAR_QA_VIEW') != 'sample-project':
        raise RuntimeError('interactive GUI QA requires synthetic sample-project')
    report = env.get('MADAR_QA_REPORT')
    if not report:
        raise RuntimeError('isolated QA report path missing')
    root = Path(report).resolve().parent
    if not root.name.startswith('.qa-v1-gui-isolated-'):
        raise RuntimeError('QA report must be inside runner-owned scratch')
    for key, parts in {
        'APPDATA': ('AppData', 'Roaming'),
        'LOCALAPPDATA': ('AppData', 'Local'),
        'WEBVIEW2_USER_DATA_FOLDER': ('WebView2',),
    }.items():
        if not env.get(key) or Path(env[key]).resolve() != root.joinpath(*parts):
            raise RuntimeError(f'{key} is not inside the runner-owned scratch')
    if not isinstance(getattr(bridge, 'connection', None), dict) or (
            bridge.connection.get('mode') != 'solo'):
        raise RuntimeError('interactive QA requires a standalone synthetic host')
    host_file = getattr(bridge, 'path', None)
    if host_file is None or not Path(host_file).resolve().is_relative_to(
            Path(env['APPDATA']).resolve()):
        raise RuntimeError('host task store must belong to isolated QA APPDATA')


def run_ui_flow(window, bridge):
    _require_isolated_qa(bridge)
    results = {}

    def evaluate(code):
        return window.evaluate_js('(function(){' + code + '})()')

    def check(name, code, *, timeout=0.0):
        deadline = time.monotonic() + timeout
        while True:
            try:
                value = evaluate(code)
                if value is True:
                    results[name] = {'pass': True, 'observed': True}
                    return
                last = {'pass': False, 'observed': value}
            except Exception as exc:
                last = {'pass': False, 'error': type(exc).__name__ + ': ' + str(exc)[:180]}
            if time.monotonic() >= deadline:
                results[name] = last
                return
            time.sleep(0.15)

    def record(name, callback):
        try:
            value = callback()
            results[name] = {'pass': value is True, 'observed': value}
        except Exception as exc:
            results[name] = {'pass': False, 'error': type(exc).__name__ + ': ' + str(exc)[:180]}

    def passed(*names):
        return all(results.get(name, {}).get('pass') is True for name in names)

    check('initial_rtl_and_board', """
      return location.pathname==='/' &&
        !!document.querySelector('.app-shell .sidebar-nav') &&
        !!document.querySelector('.task-card') &&
        (document.documentElement.dir==='rtl' ||
         document.querySelector('.app-shell')?.getAttribute('dir')==='rtl' ||
         getComputedStyle(document.body).direction==='rtl');
    """, timeout=4)
    check('accounting_nav_visible', """
      return [...document.querySelectorAll('.vitrea-primary-nav button')].some(
        b=>b.textContent.includes('حسابداری') && !b.disabled);
    """, timeout=3)

    # Capture both accounting domains. Legacy task finance and the independent
    # SQLite head must be unchanged even if the UI looks normal after navigation.
    finance_before = None
    independent_before = None
    try:
        finance_before = deepcopy(bridge._load_finance())
        results['finance_snapshot_captured'] = {'pass': True, 'observed': True}
    except Exception as exc:
        results['finance_snapshot_captured'] = {
            'pass': False, 'error': type(exc).__name__ + ': ' + str(exc)[:180]}
    try:
        head = bridge.standaloneAccountingRead()
        if not isinstance(head, dict) or not isinstance(head.get('view'), dict):
            raise ValueError('standalone host returned no accounting view')
        independent_before = deepcopy(head['view'])
        results['standalone_snapshot_captured'] = {'pass': True, 'observed': True}
        rial = independent_before.get('currency') == 'RIAL'
        results['standalone_currency_rial_head'] = {'pass': rial, 'observed': rial}
    except Exception as exc:
        results['standalone_snapshot_captured'] = {
            'pass': False, 'error': type(exc).__name__ + ': ' + str(exc)[:180]}
        results['standalone_currency_rial_head'] = {'pass': False, 'observed': False}
    if not passed('initial_rtl_and_board', 'accounting_nav_visible',
                  'finance_snapshot_captured', 'standalone_snapshot_captured',
                  'standalone_currency_rial_head'):
        return results

    check('accounting_workspace_opens', """
      const b=[...document.querySelectorAll('.vitrea-primary-nav button')].find(
        x=>x.textContent.includes('حسابداری'));
      if(!b || b.disabled)return false;
      b.click();return true;
    """)
    if not passed('accounting_workspace_opens'):
        return results

    check('accounting_workspace_fullscreen', """
      const root=document.querySelector('.sac-root[dir=rtl]');
      return location.pathname==='/accounting.html' && !!root &&
        !!root.querySelector('.sac-sidebar nav[aria-label="ناوبری میز حسابداری"]') &&
        !!root.querySelector('.sac-main') &&
        !document.querySelector('.app-shell') && !root.closest('[role=dialog]');
    """, timeout=9)
    check('accounting_overview_selected', """
      const root=document.querySelector('.sac-root');
      const selected=root?.querySelector('.sac-sidebar nav button[aria-current=page]');
      return !!selected && selected.textContent.includes('داشبورد') &&
        root.querySelector('.sac-main .sac-header h1')?.textContent.includes('داشبورد') &&
        !!root.querySelector('.sac-vtr-home');
    """, timeout=5)
    check('accounting_currency_rial_display', """
      const root=document.querySelector('.sac-root');
      return !!root &&
        root.querySelector('.sac-sidebar-footer strong')?.textContent.trim()==='ریال' &&
        root.querySelector('.sac-header-actions')?.textContent.includes('ریال') &&
        !root.querySelector('select[aria-label="واحد پولی حسابداری"]');
    """, timeout=4)
    if not passed('accounting_workspace_fullscreen', 'accounting_overview_selected',
                  'accounting_currency_rial_display'):
        return results

    check('accounting_navigation_payments', """
      const btn=[...document.querySelectorAll('.sac-sidebar nav button')].find(
        b=>b.textContent.includes('دریافت، پرداخت و اقساط'));
      if(!btn||btn.disabled)return false;btn.click();return true;
    """)
    check('accounting_payments_visible', """
      const root=document.querySelector('.sac-root');
      return !!root &&
        root.querySelector('.sac-sidebar nav button[aria-current=page]')
            ?.textContent.includes('دریافت، پرداخت و اقساط') &&
        root.querySelector('.sac-header h1')?.textContent.includes('دریافت، پرداخت و اقساط');
    """, timeout=4)
    check('accounting_navigation_reports', """
      const btn=[...document.querySelectorAll('.sac-sidebar nav button')].find(
        b=>b.textContent.includes('گزارش‌های مالی'));
      if(!btn||btn.disabled)return false;btn.click();return true;
    """)
    check('accounting_reports_visible', """
      const root=document.querySelector('.sac-root');
      return !!root &&
        root.querySelector('.sac-sidebar nav button[aria-current=page]')
            ?.textContent.includes('گزارش‌های مالی') &&
        root.querySelector('.sac-header h1')?.textContent.includes('گزارش‌های مالی');
    """, timeout=4)
    if not passed('accounting_navigation_payments', 'accounting_payments_visible',
                  'accounting_navigation_reports', 'accounting_reports_visible'):
        return results

    check('close_accounting_workspace', """
      const btn=document.querySelector('.sac-sidebar-footer button');
      if(!btn || !btn.textContent.includes('خروج از حسابداری'))return false;
      btn.click();return true;
    """)
    check('accounting_workspace_closed', """
      return location.pathname==='/index.html' &&
        !document.querySelector('.sac-root') &&
        !!document.querySelector('.app-shell .sidebar-nav') &&
        !!document.querySelector('.task-card');
    """, timeout=10)

    def unchanged():
        return finance_before is not None and bridge._load_finance() == finance_before

    def independent_unchanged():
        snapshot = bridge.standaloneAccountingRead()
        return (independent_before is not None and isinstance(snapshot, dict)
                and snapshot.get('view') == independent_before)

    record('finance_unchanged', unchanged)
    record('standalone_unchanged', independent_unchanged)

    # Do not create a task unless both independent financial snapshots were
    # unchanged and the real board reappeared after the accounting round trip.
    if not passed('accounting_workspace_closed', 'finance_unchanged',
                  'standalone_unchanged'):
        return results

    check('create_task_opens', """
      // Trello-style creation lives inside its destination list. Global
      // create shortcuts were intentionally retired by the owner.
      const btn=document.querySelector('.kanban-lane .lane-add-card');
      if(!btn||btn.disabled)return false;btn.click();return true;
    """, timeout=4)
    check('create_card_composer', """
      return !!document.querySelector('.kanban-lane form.lane-quick-add textarea')
        && !document.querySelector('.dialog[role=dialog] form.task-create');
    """, timeout=4)
    if not passed('create_task_opens', 'create_card_composer'):
        return results
    check('fill_task_title', """
      const i=document.querySelector('.lane-quick-add textarea[required]');
      if(!i)return false;
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')
        .set.call(i,'آزمون رابط تست کاربر مدار QA');
      i.dispatchEvent(new Event('input',{bubbles:true}));return true;
    """)
    time.sleep(0.2)
    check('create_task_submit', """
      const btn=document.querySelector('.lane-quick-add button[type=submit]');
      if(!btn||btn.disabled)return false;btn.click();return true;
    """)
    if not passed('fill_task_title', 'create_task_submit'):
        return results
    check('new_card_visible', """
      const card=[...document.querySelectorAll('.kanban-lane .task-card')]
        .find(c=>c.getAttribute('aria-label')==='جزئیات آزمون رابط تست کاربر مدار QA');
      return !!card && !document.querySelector('.drawer[role=dialog]');
    """, timeout=8)
    try:
        # The React card appears optimistically; persistence is debounced by
        # 320 ms and the asynchronous host write can finish still later.
        # Poll only authoritative host state. An unsaved UI card never passes.
        deadline = time.monotonic() + 8.0
        matched = []
        while True:
            saved = bridge.getState()
            matched = [task for task in saved.get('tasks', [])
                       if task.get('title') == TASK_TITLE]
            if len(matched) == 1 or len(matched) > 1 or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        results['task_saved_to_host'] = {'pass': len(matched) == 1,
                                         'observed': len(matched)}
    except Exception as exc:
        results['task_saved_to_host'] = {
            'pass': False, 'error': type(exc).__name__ + ': ' + str(exc)[:180]}
    record('finance_unchanged_after_task', unchanged)
    record('standalone_unchanged_after_task', independent_unchanged)
    return results
