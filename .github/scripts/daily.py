#!/usr/bin/env python3
"""「今日一笑」workflow 的数据准备脚本。

为什么不写成内联 shell + jq：这里每个操作都有「写错就把仓库数据搞坏」的风险
（只增不减地合并收藏、构造 featured.json），放进一个能本地跑单测的脚本里更稳妥。
GitHub 的 runner 自带 python3。

用法：
  python3 .github/scripts/daily.py outputs   <pick.json>                     # 输出 GITHUB_OUTPUT 行
  python3 .github/scripts/daily.py featured  <pick.json> <data/featured.json>
  python3 .github/scripts/daily.py favorites <favorites.json> <data/jokes.json>
"""

import json
import sys
import time


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save(path, obj, indent=1, trailing_newline=False):
    """写 JSON。

    格式必须与 collector/lib/library.mjs 逐字节一致，否则每天合并收藏都会把整个
    jokes.json 重排一遍、产生巨大且无意义的 diff：
      · jokes.json   —— JSON.stringify(list, null, 1)，**末尾无换行**
      · featured.json —— JSON.stringify(..., null, 2) + '\\n'，**末尾有换行**
    另外 Python 默认会把中文转义成 \\uXXXX，必须 ensure_ascii=False。
    """
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        if trailing_newline:
            f.write('\n')


def cmd_outputs(argv):
    """把挑段子的结果转成 key=value，交给 workflow 追加到 $GITHUB_OUTPUT"""
    p = load(argv[0])
    pairs = [('id', 'id'), ('date', 'date'), ('audioRel', 'audio'), ('vcn', 'vcn')]
    for key, out_name in pairs:
        value = p.get(key)
        if not value:
            print(f'挑段子结果缺少字段 {key}', file=sys.stderr)
            return 1
        print(f'{out_name}={value}')
    return 0


def cmd_featured(argv):
    """构造 data/featured.json（App 运行时 fetch 它）"""
    src, out = argv
    p = load(src)
    joke = {'id': p['id'], 'text': p['text']}
    # 空值不写进去，省得 featured.json 里出现一堆 null
    if p.get('category'):
        joke['category'] = p['category']
    if p.get('source'):
        joke['source'] = p['source']
    joke['date'] = p['date']
    data = {
        'date': p['date'],
        'joke': joke,
        'audio': p['audioRel'],
        'voiceName': p.get('voiceName') or '',
        'updatedAt': int(time.time() * 1000),
    }
    save(out, data, indent=2, trailing_newline=True)
    print(f"写入 {out}：{data['date']} / {joke['id']} / {data['audio']}")
    return 0


def cmd_favorites(argv):
    """把云端收藏**只增不减地**补进 data/jokes.json。

    这是「收藏的段子不能丢」的最后一环：收藏在 KV 里存的是完整快照，
    这里把它固化进仓库，这样即使 KV 被清空、换设备，收藏的段子依然在库里。
    只做追加：已存在的 id 不动、绝不删除、绝不重排 —— 出错的代价是数据丢失，不值得冒险。
    """
    fav_path, lib_path = argv
    try:
        fav = load(fav_path)
    except Exception as e:  # 云端没取到就当没有，别把整个 workflow 卡住
        print(f'收藏文件读不了（{e}），本次跳过', file=sys.stderr)
        return 0
    items = fav.get('items') if isinstance(fav, dict) else None
    if not items:
        print('云端没有收藏，跳过')
        return 0

    lib = load(lib_path)
    if not isinstance(lib, list):
        print('本地笑话库不是数组，拒绝写入', file=sys.stderr)
        return 1
    before = len(lib)

    have = {str(j.get('id')) for j in lib if isinstance(j, dict)}
    added = []
    for it in items:
        if not isinstance(it, dict):
            continue
        jid = str(it.get('id') or '')
        text = str(it.get('text') or '')
        # 没有正文的一律不收：存下来也没法恢复，只会变成一个空壳
        if not jid or not text or jid in have:
            continue
        joke = {'id': jid, 'text': text}
        if it.get('category'):
            joke['category'] = it['category']
        if it.get('source'):
            joke['source'] = it['source']
        if it.get('date'):
            joke['date'] = it['date']
        lib.append(joke)
        have.add(jid)
        added.append(jid)

    if not added:
        print(f'收藏的段子都已在库里（共 {before} 条），无需改动')
        return 0

    # 硬保护：只增不减。逻辑上不可能触发，但这条一旦写坏就是数据丢失，值得断言。
    if len(lib) < before:
        print(f'结果({len(lib)})比原来({before})短，拒绝写入', file=sys.stderr)
        return 1

    save(lib_path, lib)
    print(f'收藏入库：+{len(added)} 条 → 共 {len(lib)} 条')
    for jid in added[:10]:
        print(f'  + {jid}')
    if len(added) > 10:
        print(f'  …另外 {len(added) - 10} 条')
    return 0


COMMANDS = {'outputs': cmd_outputs, 'featured': cmd_featured, 'favorites': cmd_favorites}


def main(argv):
    if len(argv) < 2 or argv[0] not in COMMANDS:
        print(f'用法：{sys.argv[0]} {{{"|".join(COMMANDS)}}} ...', file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
