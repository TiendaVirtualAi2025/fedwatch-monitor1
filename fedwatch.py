#!/usr/bin/env python3
import json, os, re, subprocess, sys, time
from datetime import date, datetime, timezone
from pathlib import Path

CME_URL='https://www.cmegroup.cn/fed-watch/'
THRESHOLD=65.0
CHANGE=10.0
STATE=Path('fedwatch_state.json')

def pct(x):
    try: return float(str(x).replace('%','').replace('<','').replace('>','').replace('≈','').strip())
    except: return 0.0

def date_parse(s):
    s=(s or '').strip()
    m=re.match(r'(\d{1,2})\s*(\d{1,2})月\s*(\d{2,4})',s)
    if m:
        d,mo,y=map(int,m.groups()); y+=2000 if y<100 else 0
        return f'{y:04d}-{mo:02d}-{d:02d}'
    m=re.match(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2,4})',s)
    if m:
        d,mon,y=m.group(1),m.group(2),int(m.group(3)); y+=2000 if y<100 else 0
        try: return f'{y:04d}-{datetime.strptime(mon,"%b").month:02d}-{int(d):02d}'
        except: pass
    return ''

def parse_text(text):
    info={}; m=re.search(r'(\d{1,2}\s*\d{1,2}月\s*\d{4})\s+(\w+)\s+(\d{1,2}\s*\d{1,2}月\s*\d{4})\s+([\d.]+)',text)
    if not m: m=re.search(r'(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+(\w+)\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+([\d.]+)',text)
    if m: info.update(meeting_date=date_parse(m.group(1)),contract=m.group(2),mid_price=m.group(4))
    t=re.search(r'Current target rate is (\d+-\d+)',text,re.I)
    if t: info['current_target']=t.group(1)
    summary={}
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if re.match(r'EASE\s+NO\s*CHANGE\s+HIKE',line.strip(),re.I):
            for nxt in lines[i+1:i+4]:
                a=re.findall(r'[\d.]+\s*%',nxt)
                if len(a)>=3: summary={'ease':pct(a[0]),'no_change':pct(a[1]),'hike':pct(a[2])}
                break
            break
    table=[]; header=False; sub=False
    for line in lines:
        s=line.strip()
        if 'TARGET RATE' in s.upper() and 'PROBABILITY' in s.upper(): header=True; continue
        if header and not sub:
            if 'NOW' in s.upper() or '1 DAY' in s.upper(): sub=True
            continue
        if not(header and sub and s): continue
        m=re.match(r'^(\d+-\d+(?:\s*\(Current\))?)\t(.+)$',s)
        if m:
            c=re.split(r'\t+',m.group(2)); table.append({'range':m.group(1),'now':pct(c[0]) if len(c)>0 else 0,'day1':pct(c[1]) if len(c)>1 else 0})
        elif re.match(r'^\d+-\d+',s):
            p=re.split(r'\s+',s); j=next((i for i,x in enumerate(p) if '%' in x),None)
            if j is not None: table.append({'range':' '.join(p[:j]),'now':pct(p[j]),'day1':pct(p[j+1]) if len(p)>j+1 else 0})
        if s.startswith('* Data') or s.startswith('Powered by'): break
    return info,summary,table

def dom_extract(frame):
    return frame.evaluate(r'''() => {
      const find=t=>{for(const x of document.querySelectorAll('table.grid-thm')){const z=[...x.querySelectorAll('th,td')].map(e=>e.textContent.trim()).join(' ');if(z.includes(t))return x}return null};
      const pp=s=>{const m=(s||'').replace(/[%<>≈\u200b]/g,'').match(/[\d.]+/);return m?parseFloat(m[0]):0};
      const r={meeting_date:'',contract:'',mid_price:'',current_target:'',summary:{},table:[]};
      const a=find('Meeting Date'); if(a){const c=a.querySelectorAll('td');if(c.length>=4){r.meeting_date=c[0].textContent.trim();r.contract=c[1].textContent.trim();r.mid_price=c[3].textContent.trim()}}
      const b=find('Probabilities'); if(b) for(const row of b.querySelectorAll('tr')){const c=row.querySelectorAll('td');if(c.length>=3)r.summary={ease:pp(c[0].textContent),no_change:pp(c[1].textContent),hike:pp(c[2].textContent)}}
      const q=find('Target Rate (bps)'); if(q) for(const row of q.querySelectorAll('tr')){if(row.classList.contains('hide'))continue;const c=row.querySelectorAll('td');if(c.length>=2&&/^\d+-\d+/.test(c[0].textContent.trim()))r.table.push({range:c[0].textContent.trim(),now:pp(c[1].textContent),day1:pp(c[2]?.textContent)})}
      for(const e of document.querySelectorAll('*')){const m=e.textContent.match(/Current target rate is (\d+-\d+)/i);if(m){r.current_target=m[1];break}}
      return r;
    }''')

def scrape():
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    out=[]
    with sync_playwright() as p:
        b=p.chromium.launch(headless=False,args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'])
        page=b.new_page(viewport={'width':1920,'height':1080},user_agent='Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36')
        try: page.goto(CME_URL,wait_until='domcontentloaded',timeout=60000)
        except PWTimeout: print('Navigation timeout; continuing to wait for QuikStrike.')
        frame=None; end=time.time()+90
        while time.time()<end and not frame:
            for f in page.frames:
                try:
                    tx=f.inner_text('body')
                    if 'EASE' in tx and len(tx)>500: frame=f; break
                except: pass
            if not frame: time.sleep(5)
        if not frame: b.close(); raise RuntimeError('QuikStrike did not render.')
        tabs=frame.evaluate("""()=>[...document.querySelectorAll('a[id*="lbMeeting"]')].map(a=>({id:a.id,text:a.textContent.trim()}))""")
        if not tabs: b.close(); raise RuntimeError('No FOMC meeting tabs found.')
        for tab in tabs:
            try:
                ok=frame.evaluate("""id=>{const e=document.getElementById(id);if(e){e.click();return true}return false}""",tab['id'])
                if not ok: continue
                for _ in range(40):
                    time.sleep(.3)
                    if frame.evaluate("""()=>{const t=document.querySelector('.throbber,[class*="loading"]');return !t||t.offsetParent===null}"""): break
                d=dom_extract(frame)
                if not d.get('table'):
                    info,summary,table=parse_text(frame.inner_text('body')); d.update(meeting_date=info.get('meeting_date',''),contract=info.get('contract',''),mid_price=info.get('mid_price',''),current_target=info.get('current_target',''),summary=summary,table=table)
                else: d['meeting_date']=date_parse(d.get('meeting_date',''))
                if not d.get('meeting_date'): d['meeting_date']=date_parse(tab['text'])
                if d.get('meeting_date') and d.get('table'): out.append(d)
                print(d.get('meeting_date'),d.get('summary'))
            except Exception as e: print('Tab error:',e)
        b.close()
    return out

def state_load():
    try: return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    except: return {}

def notify(msg):
    topic=os.environ.get('NTFY_TOPIC','').strip()
    if not topic: raise RuntimeError('Missing GitHub Secret NTFY_TOPIC.')
    r=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','20','-X','POST','-H','Title: CME FedWatch','-H','Priority: high','-H','Tags: chart_with_upwards_trend','--data-binary','@-',f'https://ntfy.sh/{topic}'],input=msg.encode(),capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.decode(errors='replace'))

def main():
    meetings=scrape(); today=date.today().isoformat(); future=[x for x in meetings if x.get('meeting_date','')>=today]
    if not future: raise RuntimeError('No future FOMC meeting found.')
    m=min(future,key=lambda x:x['meeting_date']); s=m.get('summary',{}); vals={'hike':float(s.get('hike',0)),'hold':float(s.get('no_change',0)),'cut':float(s.get('ease',0))}; direction=max(vals,key=vals.get); prob=vals[direction]
    emoji,label={'hike':('🔴','ALZA'),'cut':('🟢','RECORTE'),'hold':('⚪','MANTENER')}[direction]
    old=state_load(); same=old.get('meeting_date')==m['meeting_date']; prev=float(old.get('probability',0)) if same and 'probability' in old else None; prevdir=old.get('direction') if same else None; prevabove=bool(old.get('above_threshold')) if same else False; above=prob>=THRESHOLD
    alert=above and (not same or prev is None or (not prevabove and above) or prevdir!=direction or (prev is not None and abs(prob-prev)>=CHANGE))
    msg=f'{emoji} {label}\nPróxima reunión Fed: {m["meeting_date"]}\nProbabilidad: {prob:.1f}%\nAlza: {vals["hike"]:.1f}%\nMantener: {vals["hold"]:.1f}%\nRecorte: {vals["cut"]:.1f}%\nUmbral: {THRESHOLD:.0f}%\nFuente: CME FedWatch / QuikStrike'
    print(msg); print('ALERTA:',alert)
    STATE.write_text(json.dumps({'meeting_date':m['meeting_date'],'probability':prob,'direction':direction,'above_threshold':above,'updated_at':datetime.now(timezone.utc).isoformat()},indent=2),encoding='utf-8')
    if alert: notify(msg)

if __name__=='__main__':
    try: main()
    except Exception as e: print('ERROR:',e); sys.exit(1)
