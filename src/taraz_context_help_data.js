/** Small, truthful, section-specific user help for the *current* Taraz UI.
 * No finance commands, client-side role elevation or invented peer receipts.
 * Labels always come from the caller's visible, host-scoped navigation.
 */
import {accountingVisibleSections} from './accounting_nav_search.js';

const guides=Object.freeze({
  overview:{
    steps:['خلاصه گردش‌ها و اسناد اخیر همین دفتر را ببینید.','برای ریزگردش یا وضعیت بدهی، از «گزارش‌های مالی» وارد شوید.'],
    caution:'مبلغ نمایشی جای تأیید اسناد و مغایرت‌گیری بانکی نیست.'
  },
  madar:{
    steps:['برای دیدن ارجاع‌ها، اجازهٔ خواندن صندوق مدار را فعال و «دریافت / بازخوانی» را انتخاب کنید.','پیشنهاد را بررسی و فقط با تأیید دوباره «بررسی شد» یا «رد ارجاع» را ثبت کنید.','اگر تصمیم قبلی ناتمام مانده، از گزینهٔ بازیابی همان تصمیم استفاده کنید.'],
    caution:'ارجاع‌های مدار فقط دادهٔ پیشنهادی‌اند و تأیید آن‌ها سند مالی، فاکتور یا پرداخت ایجاد نمی‌کند.'
  },
  company:{
    steps:['مشخصات ثبتی و سربرگ شرکت انتخاب‌شده را بررسی کنید.','اگر مجوز ویرایش دارید، اطلاعات را اصلاح و تغییرات را ذخیره کنید.'],
    caution:'این مشخصات متعلق به دفتر انتخاب‌شده است؛ تغییر شرکت عملیات جداگانه‌ای است.'
  },
  proforma:{
    steps:['طرف‌حساب، تاریخ و ردیف‌های پیش‌فاکتور را وارد کنید.','پیش‌فاکتور را ثبت کنید و پیش از تبدیل، اقلام را دوباره بررسی کنید.'],
    caution:'پیش‌فاکتور به‌تنهایی بدهی یا سند دفترکل نمی‌سازد.'
  },
  invoice:{
    steps:['از «ثبت فاکتور جدید» مشتری و ردیف‌های فروش را انتخاب و پیش‌نویس را ذخیره کنید.','در فهرست فاکتورها، پیش‌نویس را بازبینی کنید؛ تأیید و صدور دو مرحله مجزا و وابسته به مجوزند.','برای چاپ یا اصلاح سند صادرشده، همان سند را از فهرست انتخاب کنید.'],
    caution:'فقط صدور مجاز بر دفترکل اثر می‌گذارد؛ پیش‌نویس یا تأیید به‌تنهایی ثبت مالی نیست.'
  },
  invoiceDesign:{
    steps:['از کتابخانهٔ قالب‌های چاپ، یک قالب موجود یا نسخهٔ قابل ویرایش آن را انتخاب کنید.','لوگو، عنوان، محل فیلدها و اندازه‌ها را در بوم طراحی جابه‌جا و پیش‌نمایش را بررسی کنید.','در صورت داشتن مجوز، قالب را در میزبان ذخیره یا به‌عنوان پیش‌فرض انتخاب کنید.'],
    caution:'ذخیرهٔ قالب چاپ سند مالی یا فاکتور جدید نمی‌سازد؛ اطلاعات چاپ باید از فیلدهای معتبر دفتر خوانده شوند.'
  },
  bill:{
    steps:['تأمین‌کننده و ردیف‌های خرید را در «صورتحساب‌های خرید» وارد کنید.','پیش‌نویس را بازبینی کنید؛ تأیید و صدور قطعی با مجوز مناسب انجام می‌شود.'],
    caution:'سند خرید پیش از صدور، بدهی قطعی دفترکل نیست.'
  },
  contractors:{
    steps:['کار پیمانکار و وضعیت قیمت‌گذاری یا تعداد را در فهرست بررسی کنید.','پس از تطبیق مقدار و قیمت، در صورت داشتن مجوز صورتحساب تجمیعی را به‌صورت پیش‌نویس بسازید.'],
    caution:'تطبیق کار یا ساخت پیش‌نویس به معنی ثبت بدهی قطعی نیست.'
  },
  parties:{
    steps:['برای یافتن مشتری یا تأمین‌کننده، فهرست اشخاص را بررسی کنید.','در صورت مجوز، شخص تازه ثبت کنید یا برای اصلاح اطلاعات، علت تغییر را وارد کنید.'],
    caution:'مانده شخص باید با حساب کنترل و گزارش‌های دفتر تطبیق داده شود.'
  },
  migration:{
    steps:['سال مالی و فهرست سوابق واردشده پارسیان را انتخاب کنید.','فاکتورهای تاریخی و داده‌های آرشیوی را با اصل پرونده و دفترکل تطبیق دهید.'],
    caution:'سوابق آرشیوی به معنی انتقال کامل یا امکان ثبت مجدد بدون تطبیق نیست.'
  },
  cheques:{
    steps:['چک‌ها و سررسیدهای صندوق چک را بررسی کنید.','ثبت واگذاری یا وصول را مطابق وضعیت واقعی بانک و مجوز خود انجام دهید.'],
    caution:'ثبت یا واگذاری چک به‌تنهایی به معنی وصول قطعی وجه نیست.'
  },
  items:{
    steps:['کالا و کاردکس را باز کنید و گردش موجودی را بررسی کنید.','برای دریافت کالا یا حواله خروج، سند و مقدار مرتبط را با موجودی و بهای تمام‌شده تطبیق دهید.'],
    caution:'وجود فاکتور فروش لزوماً به معنی ثبت حواله خروج انبار نیست.'
  },
  settlements:{
    steps:['سند فروش یا خرید صادرشده و دارای مانده را انتخاب کنید.','دریافت یا پرداخت واقعی را با مبلغ، تاریخ و حساب درست ثبت کنید.','برای اقساط، برنامه سررسید را جدا از ثبت پرداخت بررسی کنید.'],
    caution:'برنامه اقساط به‌خودی‌خود دریافت، پرداخت یا بدهی تازه ایجاد نمی‌کند.'
  },
  cash:{
    steps:['مانده و گردش حساب صندوق یا بانک را بررسی کنید.','برای مغایرت‌گیری، ردیف صورت‌حساب بانک را با سند واقعی تطبیق دهید.'],
    caution:'ورود CSV بانک نیازمند بررسی دستی شناسه، تاریخ و مبلغ است؛ مانده دفتر تأییدیه بانک نیست.'
  },
  accounts:{
    steps:['کد و ماهیت حساب‌ها را در سرفصل‌های دفترکل پیدا کنید.','گردش و مانده هر حساب را با اسناد ثبت‌شده بررسی کنید.'],
    caution:'اصلاح دفترکل با تغییر مستقیم مانده انجام نمی‌شود؛ سند معتبر لازم است.'
  },
  journal:{
    steps:['برای سند دستی، حداقل دو ردیف بدهکار و بستانکار با مبالغ برابر وارد کنید.','برای برگشت، سند اصلی، تاریخ و علت برگشت را مشخص کنید.'],
    caution:'برگشت سند تسویه‌شده ممکن است به برگشت دریافت یا پرداخت مرتبط نیاز داشته باشد.'
  },
  reports:{
    steps:['بازه زمانی و در صورت نیاز حساب موردنظر را انتخاب کنید.','گردش، مانده اول و پایان دوره و تراز آزمایشی را بررسی کنید.','در صورت نیاز CSV گردش یا گزارش را چاپ کنید.'],
    caution:'اگر میزبان گزارش ترازسنجی‌شده ارائه نکند، گزارش قابل اتکا نمایش داده نمی‌شود.'
  },
  payroll:{
    steps:['دوره و اطلاعات حقوق یا مالیات کارکنان را بازبینی کنید.','قبل از ثبت مجاز، مبلغ و دلیل ثبت را کنترل کنید.'],
    caution:'محاسبه خودکار و تأییدشده همه نرخ‌های حقوق، بیمه و مالیات ایران در این بخش ادعا نشده است.'
  },
  period:{
    steps:['سال مالی و وضعیت اسناد باز همان دوره را بررسی کنید.','بستن دوره را فقط پس از کنترل گزارش‌ها و با مجوز مدیر انجام دهید.'],
    caution:'پس از بستن دوره، ثبت در تاریخ‌های پیشین محدود می‌شود.'
  },
  settings:{
    steps:['در تنظیمات، بخش «عمومی»، «حساب کاربری»، «اتصال به مدار» یا «اشتراک و خرید» را باز کنید.','فقط گزینه‌ای را تغییر دهید که در همین صفحه فعال و در دسترس است.'],
    caution:'نمایش گزینه‌های اشتراک و اتصال به معنی فعال‌بودن سرویس یا پرداخت نیست.'
  }
});

const subGuides=Object.freeze({
  'settings.general':{
    steps:['تم، قلم، اندازه رابط، عرض محتوا یا حرکت‌ها را انتخاب کنید.','تغییر ظاهر را در صفحه باز بررسی کنید؛ ترجیحات در اجرای بعدی هم باقی می‌ماند.']
  },
  'settings.account':{
    steps:['حساب و وضعیت نشست نمایش‌داده‌شده از میزبان را ببینید.','مدیر در صورت وجود دکمه، از «مدیریت کاربران» حساب بومی را مدیریت می‌کند.'],
    caution:'ثبت‌نام آنلاین در این نسخه راه‌اندازی نشده است.'
  },
  'settings.integration':{
    steps:['گزینه اجازه بررسی دستی ارجاع‌های مدار را فعال کنید.','«بررسی وضعیت اتصال» را بزنید و ارجاع را فقط پس از بازبینی «بررسی شد» یا «رد ارجاع» علامت بزنید.','برای تصمیم ثبت‌شده اما ناتمام، «بازیابی دستی تصمیم ناتمام» را با تأیید دوباره انجام دهید.'],
    caution:'ارجاع مدار سند مالی ایجاد نمی‌کند؛ هیچ فاکتور یا رسید رسمی به‌طور خودکار صادر نمی‌شود.'
  },
  'settings.subscription':{
    steps:['وضعیت اشتراک و اطلاعات طرح را در همین صفحه بررسی کنید.'],
    caution:'استعلام اشتراک، نمایش تعرفه و خرید در این نسخه به سرویس عملیاتی متصل نیست.'
  },
  'action.users':{
    steps:['از منوی دفتر یا «حساب کاربری»، «مدیریت کاربران» را باز کنید.','کاربر و سطح دسترسی را تنها با اختیار مدیر در میزبان بومی مدیریت کنید.'],
    caution:'عنوان شغلی یا نمایش یک دکمه جایگزین مجوز امنیتی میزبان نیست.'
  },
  'action.switchCompany':{
    steps:['پیش از تغییر شرکت، فرم‌های نیمه‌تمام را تعیین تکلیف کنید.','«تغییر شرکت» را بزنید و پیام خروج از دفتر فعلی و پشتیبان‌گیری هنگام بستن را بخوانید.'],
    caution:'تا انتخاب و احراز هویت شرکت دیگر، داده‌های این دفتر را متعلق به آن شرکت فرض نکنید.'
  },
  'action.recovery':{
    steps:['وقتی نتیجه عملیات نامشخص است، ثبت تازه را تکرار نکنید.','«بازیابی با همان شناسه عملیات» را بزنید و نتیجه میزبان را بررسی کنید.'],
    caution:'نامشخص بودن نتیجه مجوز ثبت دوباره یا اعلام وصول نیست.'
  },
  'action.approval':{
    steps:['در فهرست فروش، سند پیش‌نویس و مبلغش را بررسی کنید.','در صورت مجوز، «تأیید» را انتخاب کنید؛ صدور قطعی مرحله جداگانه است.'],
    caution:'تأیید فاکتور بدون صدور، سند دفترکل نمی‌سازد.'
  },
  'action.backup':{
    steps:['پیش از خروج یا تغییر شرکت، پیام بسته‌شدن ایمن دفتر را بررسی کنید.','برای بررسی وجود فایل پشتیبان یا بازیابی دفتر، فقط از ابزار معتبر میزبان استفاده کنید.'],
    caution:'این راهنما دکمه پشتیبان‌گیری یا بازیابی خودکار اضافه نمی‌کند.'
  },
  'action.companySecurity':{
    steps:['هنگام ورود، شرکت و نام کاربری بومی درست را انتخاب کنید.','مدیر از «مدیریت کاربران» نقش و مجوز دسترسی کاربران همان شرکت را بررسی می‌کند.'],
    caution:'مجوز مالی فقط از نشست معتبر شرکت تعیین می‌شود؛ تغییر عنوان شغلی، احراز هویت نیست.'
  },
  'action.charts':{
    steps:['در داشبورد، نمودار گردش دوره‌های اخیر و ترکیب دریافت‌ها و پرداخت‌ها را ببینید.','برای اعداد قابل ردیابی و بازه دلخواه، به «گزارش‌های مالی» بروید.'],
    caution:'نمودار خلاصه، جایگزین سند، مانده‌گیری یا مغایرت بانکی نیست.'
  }
});

export const TARAZ_ACCOUNTING_HELP_KEYS=Object.freeze(Object.keys(guides));
export const TARAZ_SETTINGS_HELP_PAGES=Object.freeze(['general','account','integration','subscription']);
export const TARAZ_HELP_ACTIONS=Object.freeze([
  'users','switchCompany','recovery','approval','backup','companySecurity','charts'
]);

const permissions={
  users:({role,capabilities})=>role==='admin'&&capabilities.canAdmin===true&&
    capabilities.usersVisible===true,
  switchCompany:({capabilities})=>capabilities.switchCompanyVisible===true,
  recovery:({capabilities})=>capabilities.recoveryVisible===true,
  approval:({role,capabilities})=>(role==='admin'||role==='editor')&&
    capabilities.canManage===true&&capabilities.approvalVisible===true,
  backup:({capabilities})=>capabilities.backupVisible===true,
  companySecurity:({role,capabilities})=>role==='admin'&&
    capabilities.canAdmin===true&&capabilities.companySecurityVisible===true,
  charts:({capabilities})=>capabilities.chartsVisible===true
};

/** Return NULL when section or action is not genuinely visible. No label guesses. */
export function resolveTarazContextHelp({
  tab,context=null,sections=[],role='viewer',sectionAccess=null,capabilities={}
}={}){
  const visible=accountingVisibleSections(sections,role,sectionAccess);
  const labels=new Map(visible);
  if(!labels.has(tab)||!Object.hasOwn(guides,tab))return null;
  if(context==null||context==='main'){
    return {id:tab,label:labels.get(tab),...guides[tab]};
  }
  if(typeof context!=='string')return null;
  if(context.startsWith('settings.')){
    if(tab!=='settings'||!Object.hasOwn(subGuides,context))return null;
    const name=context.slice('settings.'.length);
    if(!TARAZ_SETTINGS_HELP_PAGES.includes(name))return null;
    const heading={
      general:'عمومی',account:'حساب کاربری',
      integration:'اتصال به مدار',subscription:'اشتراک و خرید'
    }[name];
    return {id:context,label:labels.get(tab)+' / '+heading,...subGuides[context]};
  }
  if(!context.startsWith('action.')||!Object.hasOwn(subGuides,context))return null;
  const action=context.slice('action.'.length);
  if(!Object.hasOwn(permissions,action)||!permissions[action]({role,capabilities}))return null;
  if(action==='approval'&&tab!=='invoice')return null;
  if(action==='charts'&&tab!=='overview')return null;
  if(action==='companySecurity'&&tab!=='company'&&tab!=='settings')return null;
  if(action==='recovery'&&tab==='migration')return null;
  const headings={
    users:'مدیریت کاربران',switchCompany:'تغییر شرکت',
    recovery:'بازیابی عملیات نامشخص',approval:'تأیید فاکتور',
    backup:'پشتیبان‌گیری دفتر',companySecurity:'امنیت شرکت و کاربران',
    charts:'نمودارهای داشبورد'
  };
  return {id:context,label:headings[action],...subGuides[context]};
}

/** Test/integration helper: only authorized source nav IDs, not private records. */
export function visibleTarazHelpSections({sections=[],role='viewer',sectionAccess=null}={}){
  return accountingVisibleSections(sections,role,sectionAccess)
    .filter(([tab])=>Object.hasOwn(guides,tab))
    .map(([tab,label])=>({id:tab,label}));
}
