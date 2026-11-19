"""Riot公式日本語パッチノートの2020年以降のチャンピオン調整を収集。"""
import json
import pathlib
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'https://www.leagueoflegends.com'
START_YEAR = 2020
DELAY = 0.7
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'LoLPatchWatcher/1.2 (personal patch tracker)'})


def fetch(url):
    response = SESSION.get(url, timeout=25)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def champions():
    versions = SESSION.get('https://ddragon.leagueoflegends.com/api/versions.json', timeout=25)
    versions.raise_for_status()
    version = versions.json()[0]
    result = []
    for locale in ('ja_JP', 'en_US'):
        url = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/champion.json'
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()
        if locale == 'ja_JP':
            jp = response.json()['data']
        else:
            en = response.json()['data']
    for key, value in jp.items():
        result.append({'id': key, 'name': value['name'], 'en': en.get(key, {}).get('name', key)})
    return result


def patch_number(year):
    # 2020–2024: 10.x–14.x; 2025 onward: 25.xx, 26.xx, etc.
    return year - 2010 if year <= 2024 else year % 100


def candidates_for(year, number):
    yy = patch_number(year)
    slugs = []
    if year == 2025 and number <= 3:
        slugs.append(f'patch-25-s1-{number}-notes')
    slugs.extend((f'patch-{yy}-{number}-notes', f'patch-{yy}-{number:02d}-notes'))
    if year >= 2026:
        slugs.extend((f'league-of-legends-patch-{yy}-{number}-notes',
                      f'league-of-legends-patch-{yy}-{number:02d}-notes'))
    for slug in dict.fromkeys(slugs):
        yield f'{BASE}/ja-jp/news/game-updates/{slug}/'


def normalize(s):
    return re.sub(r'[^\w\u3040-\u30ff\u3400-\u9fff]', '', s).casefold()


def parse(html, url, version, aliases):
    soup = BeautifulSoup(html, 'html.parser')
    main = soup.select_one('article') or soup.select_one('main') or soup
    meta = soup.find('meta', property='article:published_time')
    published = meta.get('content', '')[:10] if meta else ''
    if not published:
        tag = soup.find('time')
        if tag:
            published = (tag.get('datetime', '') or tag.get_text(' ', strip=True))[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', published):
        raise ValueError('Missing reliable publication date')

    changes = []
    sr = False
    for h in main.find_all(re.compile(r'^h[2-4]$')):
        level = int(h.name[1])
        simple = normalize(h.get_text(' ', strip=True))
        if level == 2:
            sr = ('チャンピオン' in simple and
                  not any(word in simple for word in ('aram', 'ランダムミッド', 'アリーナ', 'メイヘム', 'クラシック')))
            continue
        if not sr or level != 3:
            continue
        champ = aliases.get(simple)
        if not champ:
            continue
        parts = []
        for sibling in h.next_siblings:
            if getattr(sibling, 'name', None) in ('h2', 'h3'):
                break
            if hasattr(sibling, 'get_text'):
                value = sibling.get_text(' ', strip=True)
                if value:
                    parts.append(value)
        content = '\n'.join(parts).strip()
        if content:
            changes.append({'champion_id': champ['id'], 'champion': champ['name'], 'text': content[:12000]})
    return {'version': version, 'date': published, 'url': url, 'changes': changes}


def main():
    cs = champions()
    aliases = {normalize(name): champion for champion in cs
               for name in (champion['name'], champion['en'])}
    old_file = ROOT / 'patches.json'
    previous = json.loads(old_file.read_text(encoding='utf-8')) if old_file.exists() else []
    known = {p['url'].rstrip('/'): p for p in previous if isinstance(p, dict) and p.get('url')}
    existing_versions = {str(p.get('version', '')).casefold() for p in known.values()}
    failures = []
    discovered = 0
    year_counts = {}
    for year in range(START_YEAR, date.today().year + 1):
        yy = patch_number(year)
        for number in range(1, 27):
            version = f'{yy}.{number:02d}'
            if (version.casefold() in existing_versions or
                f'{yy}.{number}'.casefold() in existing_versions or
                (year == 2025 and f'25.s1.{number}' in existing_versions)):
                continue
            found = False
            for candidate in candidates_for(year, number):
                if candidate.rstrip('/') in known:
                    found = True
                    break
                try:
                    html = fetch(candidate)
                    time.sleep(DELAY)
                    if html is None:
                        continue
                    parsed = parse(html, candidate, version, aliases)
                    if not parsed['changes']:
                        failures.append(f'{version}: no champion changes extracted ({candidate})')
                        continue
                    known[candidate.rstrip('/')] = parsed
                    existing_versions.add(version.casefold())
                    discovered += 1
                    year_counts[year] = year_counts.get(year, 0) + 1
                    print(f'{version}: {len(parsed["changes"])} champions')
                    found = True
                    break
                except (requests.RequestException, ValueError) as exc:
                    failures.append(f'{version}: {exc} ({candidate})')
                    time.sleep(DELAY)
            # Missing patches are reported at year level rather than silently ignored.
    result = sorted(known.values(), key=lambda p: (p.get('date', ''), p.get('version', '')), reverse=True)
    if not result:
        raise RuntimeError('No patch data available; refusing to overwrite with empty output')
    (ROOT / 'champions.json').write_text(json.dumps(cs, ensure_ascii=False, indent=2), encoding='utf-8')
    old_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'New patches: {discovered}; total patches: {len(result)}')
    print('New patches by year:', year_counts)
    print('Earliest stored date:', min((p.get('date', '') for p in result if p.get('date')), default='unknown'))
    if failures:
        print(f'Warnings ({len(failures)}):')
        for message in failures[:30]:
            print(' -', message)
        print('Check missing patches manually; a green workflow alone does not prove complete coverage.')


if __name__ == '__main__':
    main()
