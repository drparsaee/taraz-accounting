const KEY='taraz-ui-settings-v1';
const LEGACY_THEME='taraz-ui-theme';
export const DEFAULT_TARAZ_SETTINGS=Object.freeze({
  theme:'dark',font:'estedad',size:'normal',width:'comfortable',motion:'system'
});
const CHOICES={
  theme:['system','light','dark'],
  font:['estedad','vazirmatn','tahoma'],
  size:['compact','normal','large'],
  width:['compact','comfortable','wide'],
  motion:['system','reduce','full']
};

export function normalizeTarazSettings(value={}){
  const safe=value&&typeof value==='object'&&!Array.isArray(value)?value:{};
  return Object.fromEntries(Object.keys(DEFAULT_TARAZ_SETTINGS).map(key=>[
    key,CHOICES[key].includes(safe[key])?safe[key]:DEFAULT_TARAZ_SETTINGS[key]
  ]));
}

export function readTarazSettings(storage){
  try{
    storage=storage??globalThis.localStorage;
    const text=storage?.getItem(KEY);
    if(text)return normalizeTarazSettings(JSON.parse(text));
    const legacy=storage?.getItem(LEGACY_THEME);
    return normalizeTarazSettings({theme:CHOICES.theme.includes(legacy)?legacy:'dark'});
  }catch(_error){return {...DEFAULT_TARAZ_SETTINGS};}
}

export function effectiveTarazTheme(theme,systemDark=false){
  return theme==='system'?(systemDark?'dark':'light'):theme==='light'?'light':'dark';
}

export function applyTarazSettings(settings,root=globalThis.document?.documentElement,
    systemDark=globalThis.matchMedia?.('(prefers-color-scheme: dark)')?.matches===true){
  const clean=normalizeTarazSettings(settings);
  if(!root)return clean;
  root.dataset.theme=effectiveTarazTheme(clean.theme,systemDark);
  root.dataset.tarazFont=clean.font;
  root.dataset.tarazSize=clean.size;
  root.dataset.tarazWidth=clean.width;
  root.dataset.tarazMotion=clean.motion;
  return clean;
}

export function saveTarazSettings(value,{
  storage,root=globalThis.document?.documentElement,
  systemDark=globalThis.matchMedia?.('(prefers-color-scheme: dark)')?.matches===true,
  emit=true
}={}){
  const settings=normalizeTarazSettings(value);
  try{
    storage=storage??globalThis.localStorage;
    storage?.setItem(KEY,JSON.stringify(settings));
    storage?.setItem(LEGACY_THEME,settings.theme);
  }catch(_error){/* UI preference may be ephemeral when storage is disabled. */}
  applyTarazSettings(settings,root,systemDark);
  if(emit&&typeof globalThis.dispatchEvent==='function'&&
    typeof globalThis.CustomEvent==='function'){
    globalThis.dispatchEvent(new CustomEvent('taraz-settings-change',{detail:settings}));
  }
  return settings;
}
