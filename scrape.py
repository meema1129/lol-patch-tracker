"""Riot公式の日本語パッチノートからSRチャンピオン変更欄を抽出。"""
import json,re,time,datetime,pathlib
import requests
from bs4 import BeautifulSoup
ROOT=pathlib.Path(__file__).parent
BASE='https://www.leagueoflegends.com'
S=requests.Session();S.headers.update({'User-Agent':'LoLPatchWatcher/1.0 (personal patch tracker)'})
def get(url):
 r=S.get(url,timeout=25);r.raise_for_status();return r.text

def champions():
 versions=S.get('https://ddragon.leagueoflegends.com/api/versions.json',timeout=25).json()
 ver=versions[0];jp=S.get(f'https://ddragon.leagueoflegends.com/cdn/{ver}/data/ja_JP/champion.json',timeout=25).json()['data'];en=S.get(f'https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json',timeout=25).json()['data']
 return [{'id':key,'name':value['name'],'en':en.get(key,{}).get('name',key)} for key,value in jp.items()]

def discover():
 # Listing pages expose the official article links. Paginate while there are new results.
 urls=[];seen=set()
 for page in range(0,8):
  url=BASE+'/ja-jp/news/tags/patch-notes/'+(f'?page={page}' if page else '')
  try: soup=BeautifulSoup(get(url),'html.parser')
  except requests.RequestException: break
  new=0
  for a in soup.select('a[href]'):
   href=a.get('href','');match=re.search(r'/ja-jp/news/game-updates/league-of-legends-patch-(\d{2})-(\d+)-notes/?',href)
   if match:
    full=BASE+match.group(0)
    if full not in seen:seen.add(full);urls.append((full,f'{match.group(1)}.{match.group(2)}'));new+=1
  if page and not new:break
  time.sleep(.4)
 return urls

def parse(url,version,aliases):
 soup=BeautifulSoup(get(url),'html.parser')
 main=soup.select_one('article') or soup.select_one('main') or soup
 # Riot uses h2 for major sections and h3 for individual champion headings.
 headings=main.find_all(re.compile('^h[2-4]$'))
 sr=False;changes=[];date=''
 meta=soup.find('meta',property='article:published_time')
 if meta:date=meta.get('content','')[:10]
 if not date:
  t=soup.find('time');date=(t.get('datetime','') or t.get_text(' ',strip=True))[:10] if t else ''
 for h in headings:
  label=h.get_text(' ',strip=True);level=int(h.name[1]);simple=re.sub(r'\s+','',label)
  if level==2:
   if re.search(r'チャンピオン',simple) and not re.search(r'クラシック|メイヘム|アリーナ',simple):sr=True
   elif sr:sr=False
   continue
  if not sr or level!=3:continue
  champ=aliases.get(simple)
  if not champ:continue
  parts=[]
  for sib in h.next_siblings:
   if getattr(sib,'name',None) and re.fullmatch('h[23]',sib.name or ''):break
   if getattr(sib,'get_text',None):
    txt=sib.get_text(' ',strip=True)
    if txt:parts.append(txt)
  content='\n'.join(parts).strip()
  if content:changes.append({'champion_id':champ['id'],'champion':champ['name'],'text':content[:12000]})
 return {'version':version,'date':date,'url':url,'changes':changes}

def main():
 cs=champions();(ROOT/'champions.json').write_text(json.dumps(cs,ensure_ascii=False,indent=2),encoding='utf8')
 aliases={re.sub(r'\s+','',name):c for c in cs for name in (c['name'],c['en'])}
 previous=[]
 try:previous=json.loads((ROOT/'patches.json').read_text(encoding='utf8'))
 except (OSError,ValueError):pass
 known={p['url']:p for p in previous}
 urls=discover();print('Found',len(urls),'patch links')
 for url,version in urls:
  if url in known:continue
  try:
   p=parse(url,version,aliases);known[url]=p;print(version,len(p['changes']),'champions')
  except Exception as e:print('Failed',url,str(e))
  time.sleep(.6)
 result=sorted(known.values(),key=lambda p:tuple(map(int,p['version'].split('.'))),reverse=True)
 (ROOT/'patches.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
