"""Offline evidence-first preflight for Iranian e-invoice preparation.

This is NOT a connector or a source of current tax rates. No signing,
submitting, cancelling or modifying a taxpayer's invoice occurs here.
Regulatory rules require a separately reviewed and dated source pack.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

@dataclass(frozen=True)
class TaxEvidence:
    id:str
    title:str
    date:str
    source:str
    verified_current:bool=False


SOURCES=(
    TaxEvidence('RC_IITP.IS_V6.7','دستورالعمل صدور صورتحساب الکترونیکی',
                '1402-09','https://intamedia.ir/',False),
    TaxEvidence('RC_TICS.IS_V01','دستورالعمل فنی اتصال به سامانه مؤدیان',
                '1401-04','https://intamedia.ir/',False),
)

class TaxReviewError(ValueError):pass

def preflight_einvoice(invoice:dict[str,Any],company:dict[str,Any],*,
                       as_of:str|None=None)->dict[str,Any]:
    if not isinstance(invoice,dict) or not isinstance(company,dict):
        raise TaxReviewError('Expected invoice and company objects')
    as_of=as_of or date.today().isoformat()
    issues=[]
    def check(value,path,message):
        if not isinstance(value,str) or not value.strip():
            issues.append({'severity':'blocker','field':path,'message':message})
    check(company.get('economicCode'),'company.economicCode','شناسه اقتصادی مؤدی مشخص نیست')
    check(company.get('taxMemoryId'),'company.taxMemoryId','شناسه حافظه مالیاتی مشخص نیست')
    check(invoice.get('invoiceId'),'invoice.invoiceId','شماره/شناسه داخلی سند نامشخص است')
    check(invoice.get('issueDate'),'invoice.issueDate','تاریخ صدور مشخص نیست')
    if not isinstance(invoice.get('lines'),list) or not invoice['lines']:
        issues.append({'severity':'blocker','field':'invoice.lines','message':'اقلام فاکتور وجود ندارد'})
    else:
        for i,line in enumerate(invoice['lines']):
            if not isinstance(line,dict):
                issues.append({'severity':'blocker','field':f'lines.{i}','message':'ردیف نامعتبر است'})
                continue
            check(line.get('productServiceId'),f'lines.{i}.productServiceId',
                  'شناسه کالا/خدمت برای نگاشت سامانه مؤدیان مشخص نیست')
            for amount_key in ('quantity','unitPrice'):
                value=line.get(amount_key)
                if (type(value) not in (int, float) or
                    (type(value) is float and not isfinite(value)) or
                    (type(value) in (int, float) and (value <= 0 or value > 10**15))):
                    issues.append({'severity':'blocker','field':f'lines.{i}.{amount_key}',
                                   'message':'مقدار صحیح، مثبت، محدود و متناهی لازم است'})
    kind=invoice.get('kind','original')
    if kind not in ('original','amendment','cancellation','return'):
        issues.append({'severity':'blocker','field':'invoice.kind','message':'نوع سند ناشناخته است'})
    elif kind!='original':
        check(invoice.get('referenceTaxInvoiceId'),'invoice.referenceTaxInvoiceId',
              'سند ارجاعی مالیاتی برای این نوع صورتحساب مشخص نیست')
    issues.append({'severity':'review','field':'regulatoryRules',
       'message':'اعتبار جاری الگو، نرخ مالیات، معافیت و الزامات کسب‌وکار در منابع کنترل نشده است'})
    return {'asOf':as_of,'invoiceId':invoice.get('invoiceId'),
       'readyForSubmission':False,'submissionPermitted':False,
       'status':'review_required','issues':issues,
       'references':[{'id':s.id,'title':s.title,'date':s.date,'url':s.source,
                      'verifiedCurrent':s.verified_current} for s in SOURCES],
       'advice':'این ارزیابی مقدماتی است. تطبیق با سند رسمی روز و تأیید مسئول مالیاتی الزامی است.'}
