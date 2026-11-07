import React,{useEffect,useState} from "react";
import "./personal_parsian_company.css";

const fields=[
  ["economicCode","کد اقتصادی ثبت‌شده"],
  ["sourceRegistrationCode","کد ثبتی موجود در پارسیان (نوع شناسه نیازمند احراز)"],
  ["postalCode","کد پستی"],
  ["province","استان"],
  ["city","شهر"],
  ["address","نشانی"],
  ["phone","تلفن"],
  ["mobile","موبایل"],
];

export default function PersonalParsianCompany({api,existingProfile=null,fiscalYear='1405'}){
  const [record,setRecord]=useState(null);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(true);
  useEffect(()=>{
    let active=true;
    if(typeof api?.standaloneAccountingParsianCompany!=="function"){
      setBusy(false);setError("این نسخه به اطلاعات شرکت در بکاپ پارسیان دسترسی ندارد.");return;
    }
    Promise.resolve().then(()=>api.standaloneAccountingParsianCompany())
      .then(x=>{if(active)setRecord(x)})
      .catch(e=>{if(active)setError(String(e?.message||e))})
      .finally(()=>{if(active)setBusy(false)});
    return()=>{active=false};
  },[api]);
  if(busy)return <section className="ppc-root" role="status">در حال خواندن مشخصات شرکت از بکاپ اصلی...</section>;
  if(error)return <section className="ppc-root ppc-error" role="alert">{error}</section>;
  if(!record)return null;
  const source=(fiscalYear==='1404'?record.prior:record.latest)||{};
  return <section className="ppc-root" aria-label="اطلاعات ثبت‌شده شرکت در پارسیان">
    <div className="ppc-head">
      <div><h2>مشخصات شرکت از بکاپ پارسیان</h2><p>داده‌های ثبت‌شده در ۱۴۰۴ و ۱۴۰۵، قابل مشاهده در همین نرم‌افزار حسابداری</p></div>
      <span className="ppc-year">منبع: tbl_CoSpec / {fiscalYear}</span>
    </div>
    <dl className="ppc-grid">
      {fields.map(([key,label])=><div className="ppc-pair" key={key}>
        <dt>{label}</dt><dd dir={["economicCode","sourceRegistrationCode","postalCode","phone","mobile"].includes(key)?"ltr":"rtl"}>
          {source[key]||"در منبع ثبت نشده"}
        </dd></div>)}
      <div className="ppc-pair ppc-name">
        <dt>نام قانونی / تجاری شرکت</dt>
        <dd>{source.legalName || "در بکاپ رمزگذاری شده و نام معتبر قابل استخراج نیست"}</dd>
      </div>
    </dl>
    <div className="ppc-note" role="note">
      {existingProfile?.legalName?
        "پروفایل اجرایی شرکت در مدار نیز ثبت شده است. مقادیر بالا با منبع پارسیان قابل تطبیق‌اند.":
        "نشانی، تلفن و کدهای موجود مستقیماً از بکاپ استخراج شده‌اند. نام شرکت در فیلد CName به شکل رمزگذاری‌شده ذخیره شده است؛ برای جلوگیری از درج نام حقوقی اشتباه، پروفایل صدور فاکتور به‌صورت خودکار با نام حدسی ثبت نشده است."}
      {" "}این داده‌ها در همین نصب نگهداری و قابل مشاهده‌اند؛ ذخیره پروفایل رسمی برای صدور اسناد از فرم زیر انجام می‌شود.
    </div>
  </section>;
}
