"""Exercise real-clone local Persian chat, then prove original ledger unchanged.

The message contains no customer or accounting data. No external model is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.qa_taraz_legacy_real_clone_20261114 import _book
from taraz_desktop import open_identity_pending_legacy_workspace
from taraz_legacy_workspace_bridge import verify_workspace


def run(snapshot: Path, clone: Path) -> dict:
    snapshot, clone = snapshot.resolve(), clone.resolve()
    if clone == (Path(os.environ['APPDATA']) / 'Taraz').resolve():
        raise RuntimeError('Refusing live data usage')
    root = clone / 'roaming_taraz'
    verify_workspace(root)
    original = _book(snapshot / 'roaming_taraz' / 'standalone-accounting.sqlite3')
    if original != _book(root / 'standalone-accounting.sqlite3'):
        raise RuntimeError('Clone ledger changed before AI test')
    with patch('taraz_desktop.taraz_data_root', return_value=root):
        api, identity, token = open_identity_pending_legacy_workspace(root)
        try:
            created = api.tarazAiChatCommand({'action':'create',
                                              'title':'آزمون گفتگوی محلی نسخه جدید'})
            conversation_id = created['conversationId']
            sent = api.tarazAiChatCommand({'action':'send',
                'conversationId':conversation_id,
                'text':'سلام. این پیام فقط یک آزمایش محلی و بدون اطلاعات حساس است.'})
            if sent.get('modelRan') is True or sent.get('journalPosted') is True:
                raise RuntimeError('Unexpected model execution or financial posting')
            try:
                api.tarazAiChatCommand({'action':'approve',
                    'conversationId':conversation_id, 'actionId':'a'*32,
                    'manualConfirmation':True})
            except PermissionError:
                pass
            else:
                raise RuntimeError('Legacy viewer was unexpectedly permitted to approve finance')
        finally:
            identity.logout(token)
        reopened, reopened_identity, reopened_token = open_identity_pending_legacy_workspace(root)
        try:
            history = reopened.tarazAiChatRead(conversation_id)
            messages = history.get('messages', [])
            matches = reopened.tarazAiChatList('آزمون گفتگوی محلی')
            found = any(item['id'] == conversation_id for item in matches['conversations'])
            if len(messages) < 2 or not found:
                raise RuntimeError('Persisted Persian chat/search failed after restart')
            provider = reopened.tarazAiProviderStatus()
        finally:
            reopened_identity.logout(reopened_token)
    if original != _book(root / 'standalone-accounting.sqlite3'):
        raise RuntimeError('Financial history changed during local AI conversation')
    return {'status':'REAL_CLONE_LOCAL_PERSIAN_CHAT_PASS',
            'conversationPersistedAfterRestart':True,
            'searchRecoveredConversation':True,
            'messageCount':len(messages),
            'aiProviderMode':provider.get('mode'),
            'verifiedExternalLlm':False,
            'financialApprovalDenied':True,
            'financialLedgerUnchanged':True,
            'productionProfileChanged':False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--clone',required=True,type=Path)
    args=parser.parse_args()
    result=run(args.snapshot,args.clone)
    target=args.clone/'legacy-real-chat-verification.json'
    with target.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.flush();os.fsync(stream.fileno())
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
