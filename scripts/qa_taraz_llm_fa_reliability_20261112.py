"""Bounded actual local Ollama evaluation using synthetic Persian orders only.

No confidential source, ledger, API key, database mutation or model-generated
financial event. A rejected response is reported as rejected, not a pass.
"""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import taraz_llm_order_suggest as local

local.MODEL = 'qwen3:0.6b'
local.TIMEOUT_SECONDS = 17

cases=[
    ('explicit', 'سفارش چاپ ۱۰۰ عدد کارت، تولید ۱۲۰ عدد. مشتری و قیمت و پرت مشخص نیست.'),
    ('unknown', 'لطفاً درباره چاپ کارت مشاوره بده؛ نام مشتری، تعداد، قیمت و زمان هنوز اعلام نشده است.'),
]
rows=[]
for tag,prompt in cases:
    start=time.monotonic()
    try:
        result=local.suggest_order(prompt)
        fields=result['fields']
        grounded=(fields['customerName']=='' and fields['unit']=='' and
                  fields['quantity'] in ('','100') and
                  fields['productionQuantity'] in ('','120') and
                  result['modelRan'] is True and result['source']=='LOCAL_OLLAMA')
        # The two cases test both specific explicit numbers and unknowns.
        if tag=='unknown':
            grounded=grounded and fields['quantity']=='' and fields['productionQuantity']==''
        status='GROUNDED' if grounded else 'UNTRUSTWORTHY'
        rows.append({'case':tag,'status':status,'model':result['model'],
                     'modelRan':result['modelRan'],'missing':result['missing'],
                     'durationSeconds':round(time.monotonic()-start,2)})
    except Exception as exc:
        rows.append({'case':tag,'status':'FAIL_CLOSED','errorType':type(exc).__name__,
                     'durationSeconds':round(time.monotonic()-start,2)})
print(json.dumps({'actualLocalModel':'qwen3:0.6b','cases':rows,
                  'modelTrustedForAutonomy':all(row['status']=='GROUNDED' for row in rows),
                  'sensitiveOrRealDataSent':False},ensure_ascii=False))
