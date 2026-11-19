"""Riot公式日本語パッチノートから2020年以降の通常チャンピオン変更を収集。"""
import json
import pathlib
import re
import time
from datetime import date
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'https://www.leagueoflegends.com'
START_YEAR = 2020
DELAY = 0.7
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'LoLPatchWatcher/1.1 (personal patch tracker)'})


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
    jp_url = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/ja_JP/champion.json'
    en_url = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json'
    jp_resp = SESSION.get(jp_url, timeout=25)
    en_resp = SESSION.get(en_url, timeout=25)
    jp_resp.raise_for_status()
    en_resp.raise_for_status()
    jp = jp_resp.json()['data']
    en = en_resp.json()['data']
    for key, value in jp.items():
        result.append({'id': key, 'name': value['name'], 'en': en.get(key, {}).get('name', key)})
    return result


def patch_candidates():
    """年ごとの公式URL候補。存在しない候補は404として無視する。"""
    current = date.today().year
    for year in range(START_YEAR, current + 1):
        yy = year % 100
        for number in range(1, 27):
            # 2025年の初期3パッチはS1表記。ほかは通常の番号形式。
            slugs = [f'patch-{yy}-{number}-notes', f'patch-{yy}-{number:02d}-notes']
            if year == 2025 and number <= 3:
                slugs.insert(0, f'patch-25-s1-{number}-notes')
            if year >= 2026:
                slugs.extend([
                    f'league-of-legends-patch-{yy}-{number}-notes',
                    f'league-of-legends-patch-{yy}-{number:02d}-notes',
                ])
            for slug in dict.fromkeys(slugs):
                yield year, number, f'{BASE}/ja-jp/news/game-updates/{slug}/'


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
        label = h.get_text(' ', strip=True)
        simple = normalize(label)
        if level == 2:
            # 独立したARAM・アリーナ等のセクションは除外。
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
    # Existing records are retained; a failed request never deletes them.
    failures = []
    discovered = 0
    attempted = set()
    for year, number, url in patch_candidates():
        key = (year, number)
        if key in attempted:
            continue
        version = f'{year % 100}.{number:02d}'
        if any(re.match(rf'^{year % 100}\.(?:0?{number}|S1\.{number})$', str(p.get('version', '')), re.I)
               for p in known.values()):
            attempted.add(key)
            continue
        for candidate_year, candidate_number, candidate in candidates_for(year, number):
            if candidate.rstrip('/') in known:
                attempted.add(key)
                break
            try:
                html = fetch(candidate)
                time.sleep(DELAY)
                if html is None:
                    continue
                parsed = parse(html, candidate, version, aliases)
                # No-change patches are possible, but zero extraction can also signal layout drift.
                if not parsed['changes']:
                    failures.append(f'{version}: no champion changes extracted ({candidate})')
                    continue
                known[candidate.rstrip('/')] = parsed
                attempted.add(key)
                discovered += 1
                print(f'{version}: {len(parsed["changes"])} champions')
                break
            except (requests.RequestException, ValueError) as exc:
                failures.append(f'{version}: {exc} ({candidate})')
                time.sleep(DELAY)
        attempted.add(key)
    # Sort by publication date, avoiding assumptions about special 2025 patch numbers.
    result = sorted(known.values(), key=lambda p: (p.get('date', ''), p.get('version', '')), reverse=True)
    if not result:
        raise RuntimeError('No patch data available; refusing to overwrite with empty output')
    (ROOT / 'champions.json').write_text(json.dumps(cs, ensure_ascii=False, indent=2), encoding='utf-8')
    old_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'New patches: {discovered}; total patches: {len(result)}')
    if failures:
        print(f'Warnings ({len(failures)}):')
        for message in failures[:30]:
            print(' -', message)
        print('Check missing patches manually; a green workflow alone does not prove complete coverage.')


def candidates_for(year, number):
    yy = year % 100
    slugs = []
    if year == 2025 and number <= 3:
        slugs.append(f'patch-25-s1-{number}-notes')
    slugs.extend((f'patch-{yy}-{number}-notes', f'patch-{yy}-{number:02d}-notes'))
    if year >= 2026:
        slugs.extend((f'league-of-legends-patch-{yy}-{number}-notes',
                      f'league-of-legends-patch-{yy}-{number:02d}-notes'))
    for slug in dict.fromkeys(slugs):
        yield year, number, f'{BASE}/ja-jp/news/game-updates/{slug}/'


if __name__ == '__main__':
    main()

