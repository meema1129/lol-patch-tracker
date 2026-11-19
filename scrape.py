        raise ValueError('Missing reliable publication date')

    # The 12.10 page puts individual champion headings at h4, including
    # mid-patch follow-up changes before the main champion section.
    is_durability = version == '12.10'
    changes = {}
    sr = False
    midpatch = False
    category = ''
    headings = main.find_all(re.compile(r'^h[2-4]$'))
    for h in headings:
        level = int(h.name[1])
        label = h.get_text(' ', strip=True)
        simple = normalize(label)
        if level == 2:
            midpatch = 'ミッドパッチ' in simple
            sr = ('チャンピオン' in simple and
                  not any(word in simple for word in ('aram', 'ランダムミッド', 'アリーナ', 'メイヘム', 'クラシック')))
            category = ''
            continue
        if level == 3 and is_durability and midpatch:
            # Only follow-up balance changes, not ARAM/ARURF or bug fixes.
            category = 'balance' if ('耐久力' in simple and 'フォローアップ' in simple) else ''
            continue
        if not (sr or (is_durability and midpatch and category == 'balance')):
            continue
        if level not in (3, 4):
            continue
        champ = aliases.get(simple)
        if not champ:
            continue
        content = section_text(h)
        if not content:
            continue
        entry = changes.setdefault(champ['id'], {'champion_id': champ['id'], 'champion': champ['name'], 'text': ''})
        prefix = '【ミッドパッチ調整】\n' if midpatch else ''
        addition = prefix + content[:12000]
        entry['text'] = (entry['text'] + '\n\n' + addition).strip()[:20000]

    if is_durability:
        # Universal stat changes apply to all champions, not just those with
        # individual entries. Thresh has an explicit exception in the article.
        universal = ('【全チャンピオン共通：耐久力アップデート】\n'
                     '基本体力 +70\n'
                     'レベルアップごとの体力 +14\n'
                     'レベルアップごとの物理防御 +1.2\n'
                     'レベルアップごとの魔法防御 +0.8\n'
                     '※スレッシュには独自の調整あり。詳細は公式パッチノート参照。')
        for champ in cs:
            entry = changes.setdefault(champ['id'], {'champion_id': champ['id'], 'champion': champ['name'], 'text': ''})
            entry['text'] = (universal + ('\n\n' + entry['text'] if entry['text'] else ''))[:20000]

    return {'version': version, 'date': published, 'url': url, 'changes': list(changes.values())}


def main():
    cs = champions()
    aliases = {normalize(name): champion for champion in cs for name in (champion['name'], champion['en'])}
    old_file = ROOT / 'patches.json'
    previous = json.loads(old_file.read_text(encoding='utf-8')) if old_file.exists() else []
    known = {p['url'].rstrip('/'): p for p in previous if isinstance(p, dict) and p.get('url')}
    failures = []
    added = Counter()
    # 12.10 must be refreshed even if an old empty record exists.
    for year in range(START_YEAR, date.today().year + 1):
        yy = patch_number(year)
        for number in range(1, 27):
            version = f'{yy}.{number:02d}'
            existing = [p for p in known.values() if str(p.get('version', '')).lower() in
                        {version.lower(), f'{yy}.{number}', f'25.s1.{number}' if year == 2025 else ''}]
            if existing and not (year == 2022 and number == 10):
                continue
            for url in candidates_for(year, number):
                try:
                    html = fetch(url)
                    time.sleep(DELAY)
                    if html is None:
                        continue
                    parsed = parse(html, url, version, aliases, cs)
                    if not parsed['changes']:
                        failures.append(f'{version}: no champion changes extracted ({url})')
                        continue
                    known[url.rstrip('/')] = parsed
                    if not existing:
                        added[year] += 1
                    print(f'{version}: {len(parsed["changes"])} champions')
                    break
                except (requests.RequestException, ValueError) as exc:
                    failures.append(f'{version}: {exc} ({url})')
                    time.sleep(DELAY)
            else:
                # A known, empty-change patch such as 11.23 is not necessarily an error.
                pass

    result = sorted(known.values(), key=lambda p: (p.get('date', ''), p.get('version', '')), reverse=True)
    if not result:
        raise RuntimeError('No patch data available; refusing to overwrite with empty output')
    if not any(p.get('version') == '12.10' and p.get('changes') for p in result):
        raise RuntimeError('Patch 12.10 was not recovered; refusing to save incomplete data')
    (ROOT / 'champions.json').write_text(json.dumps(cs, ensure_ascii=False, indent=2), encoding='utf-8')
    old_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'New patches: {sum(added.values())}; total patches: {len(result)}')
    print('New patches by year:', dict(sorted(added.items())))
    print('Earliest stored date:', min(p.get('date', '') for p in result))
    print('Patch 12.10 champion entries:', next(len(p['changes']) for p in result if p['version'] == '12.10'))
    if failures:
        print(f'Warnings ({len(failures)}):')
        for message in failures[:30]:
            print(' -', message)


if __name__ == '__main__':
    main()
