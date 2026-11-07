import os
from pathlib import Path
p=Path(os.environ['LOCALAPPDATA'])/'MadarDesk-Private'/'Parsian-Migration-20261107'/'personal-app-build'/'src'
f=p/'standalone_accounting_workspace.jsx'
s=f.read_text('utf-8')
old="""  const historicalPartyAccounts=sortMap(parties).map(p=>{
    const legacyId=p.id.startsWith('ps.party.')?p.id.replace('ps.party.','ps.'):null;
    return {...p,legacyId,historicRial:legacyId?accounts[legacyId]?.debitMinusCredit??0:0};
  });"""
assert s.count(old)==1
new="""  // A Parsian party ID is ps.parsian.1405.party.12.2.N.
  // Its posted GL counterpart is ps.parsian.account.t.12.2.N.
  // The previous mapping only matched ps.party.* and silently displayed zero.
  const historicalPartyAccounts=sortMap(parties).map(p=>{
    const prefix='ps.parsian.1405.party.';
    const suffix=p.id.startsWith(prefix)?p.id.slice(prefix.length):'';
    const postingId=/^12\.2\.[0-9]+$/.test(suffix)?
      'ps.parsian.account.t.'+suffix:null;
    const account=postingId?accounts[postingId]:null;
    return {...p,legacyId:account?postingId:null,
      historicRial:account?.debitMinusCredit??0,
      originalParsianCode:suffix||null};
  });"""
s=s.replace(old,new)
anchor="""          {tab==='parties'&&<>"""
assert s.count(anchor)==1
s=s.replace(anchor,anchor+"\n            <PersonalParsianInvoices api={api} section=\"parties\"/>")
f.write_text(s,'utf-8')
print('NATIVE_PERSON_GL_MAPPING_AND_HISTORY_WIRED')
