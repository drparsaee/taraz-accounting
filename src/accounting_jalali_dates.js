/** Persian-calendar UI adapter, with canonical Gregorian YYYY-MM-DD persistence.
 * Uses the runtime ICU Persian calendar for both directions, so leap days are
 * validated by round-tripping against the exact same calendar engine.
 * No dates, locale preferences or timezones are sent to a remote service.
 */
const isoDay=/^\d{4}-\d{2}-\d{2}$/;
const jalaliText=/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/;
const calendar=new Intl.DateTimeFormat('en-US-u-ca-persian-nu-latn',{
  year:'numeric',month:'2-digit',day:'2-digit',timeZone:'UTC',
});

export const normalizePersianDigits=value=>String(value??'')
  .replace(/[۰-۹]/g,x=>String(x.charCodeAt(0)-0x06f0))
  .replace(/[٠-٩]/g,x=>String(x.charCodeAt(0)-0x0660))
  .replace(/\u200c/g,'').trim();

function utcDay(iso){
  if(!isoDay.test(iso))return null;
  const [y,m,d]=iso.split('-').map(Number);
  const instant=new Date(Date.UTC(y,m-1,d,12));
  return instant.getUTCFullYear()===y && instant.getUTCMonth()===m-1 &&
    instant.getUTCDate()===d ? instant : null;
}
function pad(n){return String(n).padStart(2,'0');}
function getPersianDate(instant){
  const result={};
  for(const part of calendar.formatToParts(instant)){
    if(['year','month','day'].includes(part.type))result[part.type]=Number(part.value);
  }
  if(!result.year||!result.month||!result.day)
    throw Error('Persian calendar unavailable in WebView2');
  return [result.year,result.month,result.day];
}
export function formatAccountingJalali(iso,{digits='fa'}={}){
  if(!iso)return '';
  const instant=utcDay(iso);
  if(!instant)return '';
  const [year,month,day]=getPersianDate(instant);
  const value=year+'/'+pad(month)+'/'+pad(day);
  return digits==='ascii'?value:value.replace(/[0-9]/g,
    x=>'۰۱۲۳۴۵۶۷۸۹'[Number(x)]);
}
/** Reject impossible Persian dates, including leap-year Esfand 30. */
export function parseAccountingJalali(value){
  const text=normalizePersianDigits(value);
  const match=jalaliText.exec(text);
  if(!match)return null;
  const [year,month,day]=match.slice(1).map(Number);
  if(year<1200||year>1599||month<1||month>12||day<1||day>31)return null;
  const target=year*10000+month*100+day;
  // A solar year jy lies between Gregorian jy+620 and jy+623.
  let low=Math.floor(Date.UTC(year+620,0,1,12)/86400000);
  let high=Math.floor(Date.UTC(year+623,0,1,12)/86400000);
  while(low<=high){
    const mid=low+Math.floor((high-low)/2);
    const instant=new Date(mid*86400000);
    const [y,m,d]=getPersianDate(instant);
    const current=y*10000+m*100+d;
    if(current===target){
      const iso=instant.toISOString().slice(0,10);
      return formatAccountingJalali(iso,{digits:'ascii'})===
        year+'/'+pad(month)+'/'+pad(day)?iso:null;
    }
    if(current<target)low=mid+1;else high=mid-1;
  }
  return null;
}
export const displayAccountingDate=(iso)=>formatAccountingJalali(iso)||'تاریخ نامعتبر';
