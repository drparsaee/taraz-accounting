'use strict';
/** Differential QA: real compiled JS print validator vs Python template store. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const esbuild=require('esbuild');

const root=path.resolve(__dirname,'..');
const filename=path.join(root,'src/accounting_print_template.js');
const compiled=esbuild.buildSync({entryPoints:[filename],platform:'node',format:'cjs',bundle:true,
  write:false,loader:{'.css':'empty'},logLevel:'silent'}).outputFiles[0].text;
const exposed={exports:{}};
const fromSource=require('node:module').createRequire(filename);
new Function('require','module','exports',compiled)(fromSource,exposed,exposed.exports);
const {DEFAULT_PRINT_TEMPLATE,validatePrintTemplate}=exposed.exports;

function asCases(){
  const cases=[];
  const add=(label,mutate)=>{
    const document=structuredClone(DEFAULT_PRINT_TEMPLATE);
    mutate(document);
    cases.push({label,document});
  };
  add('default',()=>{});
  for(const page of ['A4','A5'])for(const orientation of ['portrait','landscape'])
    for(const margin of [3,10,30])for(const rowHeight of [6,8.5,14])
      for(const y of [30,60,75,100,125,150,190,225,249]){
        add(`paper/${page}/${orientation}/m${margin}/h${rowHeight}/y${y}`,d=>{
          d.page=page;d.orientation=orientation;d.margin=margin;
          d.table.rowHeight=rowHeight;d.table.y=y;
        });
      }
  const variants=[
    ['empty title',d=>d.title=''],
    ['whitespace title',d=>d.title='    '],
    ['trailing-space overlong title',d=>d.title='T'.repeat(100)+'   '],
    ['emoji overlong title',d=>d.title='🧾'.repeat(51)],
    ['emoji overlong signature',d=>d.signature='🧾'.repeat(51)],
    ['emoji overlong field label',d=>d.fields[0].label='🧾'.repeat(31)],
    ['emoji overlong company header',d=>d.companyHeader='🧾'.repeat(61)],
    ['emoji overlong footer',d=>d.footerText='🧾'.repeat(36)],
    ['emoji overlong column heading',d=>d.table.labels.description='🧾'.repeat(13)],
    ['empty trim-BOM title',d=>d.title='\ufeff'],
    ['empty trim-BOM column heading',d=>d.table.labels.description='\ufeff'],
    ['valid custom source',d=>{
      d.table.customColumns=[{id:'custom_1',label:'واحد شخصی',source:'unit'}];
      d.table.columns=['description','quantity','custom_1','total'];
    }],
    ['valid four custom sources',d=>{
      d.table.customColumns=[1,2,3,4].map(n=>({
        id:'custom_'+n,label:'ستون '+n,source:['unit','quantity','itemId','total'][n-1]}));
      d.table.columns=['description',...d.table.customColumns.map(c=>c.id)];
    }],
    ['undefined custom column',d=>{d.table.columns=['description','custom_1'];}],
    ['duplicate custom ID',d=>{d.table.customColumns=[
      {id:'custom_1',label:'الف',source:'unit'},
      {id:'custom_1',label:'ب',source:'quantity'}];}],
    ['invalid custom field',d=>{d.table.customColumns=[{id:'custom_6',label:'وزن',source:'unit'}];}],
    ['invalid custom source',d=>{d.table.customColumns=[{id:'custom_1',label:'اشتباه',source:'eval'}];}],
    ['custom too-long emoji',d=>{d.table.customColumns=[{id:'custom_1',label:'🎁'.repeat(13),source:'unit'}];}],
    ['custom extra executable key',d=>{d.table.customColumns=[{id:'custom_1',label:'خوب',source:'unit',script:'doWork()'}];}],
    ['custom string instead of array',d=>{d.table.customColumns='custom_1';}],
    ['custom prototype-like ID',d=>{d.table.customColumns=[{id:'__proto__',label:'ناامن',source:'unit'}];}],
    ['negative margin',d=>d.margin=-1],
    ['NaN-like margin',d=>d.margin='NaN'],
    ['invalid font',d=>d.font='SomeRemoteFont'],
    ['invalid color',d=>d.color='rgb(2,3,4)'],
    ['missing signature',d=>delete d.signature],
    ['duplicate print field',d=>d.fields[1].id='title'],
    ['bool coordinate',d=>d.fields[0].x=true],
    ['too big label',d=>d.fields[0].label='X'.repeat(61)],
    ['weird page',d=>d.page='A3'],
    ['invalid rowHeight',d=>d.table.rowHeight=100],
    ['false price',d=>d.table.showPrice='false'],
    ['column duplicate',d=>d.table.columns=['description','description']],
    ['missing description column',d=>d.table.columns=['quantity','total']],
    ['illegal column',d=>d.table.columns=['description','evil']],
    ['illegal heading key',d=>d.table.labels.evil='bad'],
    ['bad heading',d=>d.table.labels.description=' '],
    ['metadata length',d=>d.companyHeader='X'.repeat(121)],
    ['off page logo',d=>d.logoLayout.x=208],
    ['off page logo height',d=>d.logoLayout.height=300],
    ['malformed logo',d=>d.logo='file:///secret'],
    ['A5 table too low',d=>{d.page='A5';d.table.y=205;}],
    ['legacy optional layout',d=>{delete d.logoLayout;delete d.companyHeader;
      delete d.companySubtitle;delete d.footerText;delete d.table.columns;
      delete d.table.rowHeight;}],
  ];
  for(const [label,change] of variants)add(label,change);
  return cases;
}

test('full page/column/logo/legacy JS-Python print-validator agreement',()=>{
  const cases=asCases();
  const js=cases.map(({document})=>{try{validatePrintTemplate(document);return true;}
    catch{return false;}});
  const python=[
    'import json,sys',
    'from standalone_accounting_template_store import _validate_print_design',
    'result=[]',
    'for data in json.load(sys.stdin):',
    ' try:',
    '  _validate_print_design(data)',
    '  result.append(True)',
    ' except (ValueError,TypeError,KeyError):',
    '  result.append(False)',
    'print(json.dumps(result))',
  ].join('\n');
  const proc=spawnSync('py',['-3.12','-B','-c',python],{
    cwd:root,encoding:'utf8',input:JSON.stringify(cases.map(x=>x.document)),
    maxBuffer:2*1024*1024,timeout:15000,
    env:{...process.env,PYTHONUTF8:'1'}});
  assert.equal(proc.status,0,proc.stderr);
  const py=JSON.parse(proc.stdout);
  assert.equal(py.length,js.length);
  const mismatches=[];
  cases.forEach(({label},i)=>{if(js[i]!==py[i])mismatches.push({label,js:js[i],py:py[i]});});
  assert.deepEqual(mismatches,[],'Native Python and JS must agree on every submitted template');
  assert.ok(js.filter(Boolean).length>=100);
  assert.ok(js.filter(v=>!v).length>=100);
});
