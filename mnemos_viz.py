#!/usr/bin/env python3
"""Mnemos 记忆图谱 v5.0 — 全中文交互式社区聚类图谱 (ECharts)
增强功能：
  - 全中文界面
  - 记忆健康仪表盘
  - 衰减热力图时间线
  - 实体关系增强
  - 搜索高亮 + 快捷键
  - 暗色主题优化
用法：
  python3 mnemos_viz.py                       # 生成并打开
  python3 mnemos_viz.py --no-open             # 仅生成
  python3 mnemos_viz.py --output /path.html   # 自定义输出
  python3 mnemos_viz.py --serve               # 启动HTTP服务器(端口9730)
"""
import sqlite3, os, json, sys, math, webbrowser, argparse, http.server, socketserver, threading, base64
from datetime import datetime, timedelta
from collections import Counter, defaultdict

DB = os.path.expanduser('~/.hermes/mnemos.db')
OUT = os.path.expanduser('~/.hermes/memory_viz.html')
VIS_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'echarts.min.js')
VERBOSE = False

TIER_LABELS = {'impression': '印象', 'context': '上下文', 'core': '核心', 'belief': '信念'}
TIER_COL = {'impression': '#4FC3F7', 'context': '#66BB6A', 'core': '#FFA726', 'belief': '#EF5350'}
ENT_LABELS = {'concept': '概念', 'person': '人物', 'project': '项目', 'technology': '技术', 'location': '地点', '': '其他'}
ENT_COL = {'concept': '#CE93D8', 'person': '#FF8A65', 'project': '#4DB6AC', 'technology': '#90A4AE', 'location': '#AED581', '': '#78909C'}
COMM_PAL = ['#7C4DFF', '#00BCD4', '#FF6D00', '#69F0AE', '#FF5252', '#FFD740', '#448AFF', '#B388FF', '#64FFDA', '#FF80AB']


def compute_pagerank(edges):
    adj = defaultdict(list); nodes = set()
    for e in edges:
        f, t = e['from_id'], e['to_id']; w = float(e['weight'] if e['weight'] is not None else 1.0)
        adj[f].append((t, w)); adj[t].append((f, w)); nodes.add(f); nodes.add(t)
    if not nodes: return {}
    n = len(nodes); pr = {nd: 1.0 / n for nd in nodes}; damping = 0.85
    for _ in range(30):
        new_pr = {}; total_diff = 0.0
        for nd in nodes:
            s = sum(pr[nb] * w for nb, w in adj.get(nd, []))
            npr = (1 - damping) / n + damping * s; new_pr[nd] = npr; total_diff += abs(npr - pr[nd])
        pr = new_pr
        if total_diff < 1e-6: break
    mx = max(pr.values()) if pr else 1
    return {k: v / mx for k, v in pr.items()}


def compute_communities(edges):
    adj = defaultdict(list); nodes = set()
    for e in edges:
        f, t = e['from_id'], e['to_id']; w = float(e['weight'] if e['weight'] is not None else 1.0)
        adj[f].append((t, w)); adj[t].append((f, w)); nodes.add(f); nodes.add(t)
    if not nodes: return {}
    labels = {n: n for n in adj}
    for _ in range(10):
        for nd in list(adj.keys()):
            if not adj[nd]: continue
            lw = {}
            for nb, w in adj[nd]:
                lbl = labels[nb]; lw[lbl] = lw.get(lbl, 0) + w
            if lw: labels[nd] = max(lw, key=lw.get)
    uniq = sorted(set(labels.values())); cm_id = {u: i for i, u in enumerate(uniq)}
    return {nd: cm_id[lbl] for nd, lbl in labels.items()}


def load():
    if not os.path.exists(DB): print(f"数据库未找到: {DB}"); sys.exit(1)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    imp = c.execute("SELECT * FROM impressions ORDER BY created_at ASC").fetchall()
    ent = c.execute("SELECT * FROM entity_index").fetchall()
    edg = c.execute("SELECT * FROM entity_edges ORDER BY weight DESC").fetchall()
    pr = {}; cm = {}
    try:
        r = c.execute("SELECT value FROM temporal_states WHERE state_key='graph_pagerank'").fetchone()
        if r: pr = json.loads(r['value'])
    except: pass
    try:
        r = c.execute("SELECT value FROM temporal_states WHERE state_key='graph_communities'").fetchone()
        if r: cm = json.loads(r['value'])
    except: pass
    c.close()
    if not cm: cm = compute_communities(edg)
    if not pr: pr = compute_pagerank(edg)
    if VERBOSE: print(f"加载: {len(imp)} 记忆 | {len(ent)} 实体 | {len(edg)} 边 | {len(set(cm.values()))} 社区")
    return imp, ent, edg, pr, cm


def build(imp, ent, edg, pr, cm):
    nodes, edges_l = [], []
    nids = set(); eids_map = {}; mem_ents = defaultdict(set)
    comm_ents = defaultdict(list); comm_mems = defaultdict(list)

    for e in ent:
        lbl = e['label']
        if lbl not in eids_map:
            eids_map[lbl] = {'etype': e['etype'], 'mem_ids': set(), 'cnt': 0, 'comm': cm.get(lbl, -1)}
        eids_map[lbl]['mem_ids'].add(e['memory_id'][:12]); eids_map[lbl]['cnt'] += 1

    for lbl, info in eids_map.items():
        cid = info['comm']
        if cid >= 0: comm_ents[cid].append(lbl)

    for e in ent: mem_ents[e['memory_id'][:12]].add(e['label'])

    for imp_ in imp:
        mid = f"mem_{imp_['entry_id'][:12]}"
        els = sorted(mem_ents.get(imp_['entry_id'][:12], set()))
        comms = [cm.get(l, -1) for l in els]
        mc = max(set(comms), key=comms.count) if comms else -1
        if mc >= 0: comm_mems[mc].append(mid)

    # 社区节点
    for cid in sorted(set(cm.values())):
        if cid < 0: continue
        ents_in = comm_ents.get(cid, []); mems_in = comm_mems.get(cid, [])
        pr_sc = sum(pr.get(e, 0) for e in ents_in)
        col = COMM_PAL[cid % len(COMM_PAL)]; sz = 36 + min(len(ents_in) * 2.5, 44)
        nodes.append(dict(id=f"comm_{cid}", label=f"C{cid}",
            title=f"<b>社区 {cid}</b><br>实体: {len(ents_in)} | 记忆: {len(mems_in)}<br>PageRank总和: {pr_sc:.3f}",
            color=dict(background=col, border='#ffffff', highlight=dict(background=col, border='#fff')),
            shape='hexagon', size=sz, font=dict(size=16, color='#ffffff', face='Arial', strokeWidth=4, strokeColor='#080c18'),
            borderWidth=3, group='community', community=cid, entity_count=len(ents_in), memory_count=len(mems_in),
            shadow=dict(enabled=True, color=col, size=20, x=0, y=0)))
        nids.add(f"comm_{cid}")

    # 实体节点
    for lbl, info in eids_map.items():
        eid = f"ent_{lbl}"; nids.add(eid)
        cid = info['comm']; et = info['etype'] or ''
        col = ENT_COL.get(et, '#78909C'); bcol = COMM_PAL[cid % len(COMM_PAL)] if cid >= 0 else col
        sz = 12 + min(info['cnt'] * 1.5, 22) + min(pr.get(lbl, 0) * 60, 18)
        et_cn = ENT_LABELS.get(et, et)
        nodes.append(dict(id=eid, label=lbl,
            title=f"<b>{lbl}</b><br>类型: {et_cn}<br>记忆: {len(info['mem_ids'])} | 提及: {info['cnt']}次<br>PageRank: {pr.get(lbl, 0):.4f} | 社区 {cid}",
            color=dict(background=col, border=bcol, highlight=dict(background=col, border='#fff')),
            shape='ellipse', size=sz, font=dict(size=max(11, min(12 + info['cnt'], 20)), color='#c9d1d9', strokeWidth=3, strokeColor='#080c18'),
            borderWidth=2 if cid >= 0 else 1, group='entity', etype=et, etype_cn=et_cn, mention_cnt=info['cnt'],
            mem_cnt=len(info['mem_ids']), community=cid, pageRank=pr.get(lbl, 0),
            shadow=dict(enabled=True, color=bcol, size=8, x=0, y=0)))
        if cid >= 0:
            edges_l.append(dict(from_=f"comm_{cid}", to=eid, color=dict(opacity=0.08), width=0.1, title="聚类"))

    # 记忆节点
    for imp_ in imp:
        eid = f"mem_{imp_['entry_id'][:12]}"; nids.add(eid)
        t = imp_['tier'] or 'impression'; col = TIER_COL.get(t, '#90CAF9')
        d = imp_['decay'] or 0.0; h = imp_['hits'] or 0; cr = (imp_['created_at'] or '')[:19]
        sz = 7 + min(h, 10) * 0.6 + (5 if t in ('core', 'belief') else 0); sz = max(7, min(sz, 24))
        ctxt = (imp_['content'] or '')
        els = sorted(mem_ents.get(imp_['entry_id'][:12], set()))
        comms = [cm.get(l, -1) for l in els]
        mc = max(set(comms), key=comms.count) if comms else -1
        bcol = COMM_PAL[mc % len(COMM_PAL)] if mc >= 0 else col
        t_cn = TIER_LABELS.get(t, t)
        nodes.append(dict(id=eid, label=ctxt[:40] + ('...' if len(ctxt) > 40 else ''),
            title=f"<b>{imp_['title'] or ''}</b><br>{ctxt[:180]}<br>时间: {cr} | 衰减: {d:.2f} | 分层: {t_cn} | 社区 {mc}",
            color=dict(background=col, border='rgba(255,255,255,0.15)', highlight=dict(background='#a371f7', border='#fff')),
            shape='box', size=sz, font=dict(size=9, color='#8b949e'),
            borderWidth=0.5, group='memory', tier=t, tier_cn=t_cn, decay=d, hits=h, created=cr,
            community=mc, entities=els, content=ctxt[:400], mem_type=imp_['memory_type'] or '',
            shadow=dict(enabled=True, color=col, size=4, x=0, y=0)))
        for lbl in els:
            tid = f"ent_{lbl}"
            if tid in nids:
                edges_l.append(dict(from_=eid, to=tid, color=dict(opacity=0.15), width=0.3, title="关联"))
        if mc >= 0:
            edges_l.append(dict(from_=eid, to=f"comm_{mc}", color=dict(opacity=0.05), width=0.1, title="归属"))

    # 实体间边
    eset = set()
    for ed in edg:
        f = f"ent_{ed['from_id']}"; t = f"ent_{ed['to_id']}"
        if f in nids and t in nids:
            k = tuple(sorted([f, t]))
            if k not in eset:
                eset.add(k); w = ed['weight']
                edges_l.append(dict(from_=f, to=t, width=min(max(w * 2, 0.3), 5),
                    color=dict(opacity=min(0.2 + w * 0.1, 0.7), color='#78909C'),
                    smooth=dict(type='continuous', forceDirection='none', roundness=0.5),
                    title=f"{ed['from_id']} <-> {ed['to_id']} (权重={w:.1f})"))

    seen = set(); edges = []
    for e in edges_l:
        k = (e['from_'], e['to'])
        if k not in seen: seen.add(k); edges.append(e)

    if VERBOSE: print(f"图谱: {len(nodes)} 节点, {len(edges)} 边")
    return nodes, edges


def stats_summary(imp, ent, edg, pr, cm):
    etype_cn_map = {'concept': '概念', 'person': '人物', 'project': '项目', 'technology': '技术', 'location': '地点', '': '其他', 'unknown': '未知'}
    etype_cnt = Counter(etype_cn_map.get(e['etype'] or 'unknown', e['etype'] or '其他') for e in ent)
    decay_buckets = [(0, 0.15, '新鲜'), (0.15, 0.4, '微弱'), (0.4, 0.6, '中等'), (0.6, 0.8, '衰减'), (0.8, 0.95, '临界'), (0.95, 1.1, '遗忘')]
    decay_dist = [0] * len(decay_buckets)
    for im in imp:
        d = im['decay'] or 0
        for i, (lo, hi, _) in enumerate(decay_buckets):
            if lo <= d < hi: decay_dist[i] += 1; break
    tag_cnt = Counter()
    for im in imp:
        try: tags = json.loads(im['tags_json'] or '[]')
        except: continue
        for t in tags: tag_cnt[t] += 1
    top_tags = tag_cnt.most_common(20)
    comm_sizes = Counter(cm.values()) if cm else {}
    top_pr = sorted(pr.items(), key=lambda x: -x[1])[:10]
    # 健康指标
    total = len(imp) if imp else 1
    healthy = sum(1 for i in imp if (i['decay'] or 0) < 0.6)
    risk = sum(1 for i in imp if 0.6 <= (i['decay'] or 0) < 0.95)
    lost = sum(1 for i in imp if (i['decay'] or 0) >= 0.95)
    health_score = round(healthy / total * 100)
    return dict(mem_total=len(imp), ent_total=len(ent), edge_total=len(edg),
        comm_total=len(comm_sizes), ent_types=sorted(etype_cnt.items()),
        decay_buckets=[(lbl, decay_dist[i]) for i, (_, _, lbl) in enumerate(decay_buckets)],
        top_tags=top_tags, comm_sizes=sorted(comm_sizes.items(), key=lambda x: -x[1])[:10], top_pr=top_pr,
        health_score=health_score, healthy=healthy, risk=risk, lost=lost)


def load_vis_js():
    # echarts — 直接用 CDN，本地静态文件需要额外路由
    return '<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>'


def gen_html(nodes, edges, s, vis_src='https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js', data_url='/api/mnemos/viz-data'):
    """Generate compact HTML with external vis-network + fetch-based data loading."""
    if not nodes or not edges:
        return '<html><body><h2>暂无数据</h2></body></html>'
    ent_rows = ''.join('<div class="sr"><span class="sdot" style="background:%s"></span>%s<span class="sv">%s</span></div>' %
        (ENT_COL.get(k, '#78909C'), k, v) for k, v in s['ent_types'])
    decay_rows = ''.join('<div class="sr"><span class="sdot" style="background:%s"></span>%s<span class="sv">%s</span></div>' %
        (['#4FC3F7', '#66BB6A', '#FFA726', '#FF7043', '#EF5350', '#B71C1C'][i], l, c) for i, (l, c) in enumerate(s['decay_buckets']))
    tag_rows = ''.join('<span class="tag" style="font-size:%spx">%s(%s)</span>' %
        (str(max(9, min(8 + c * 2, 18))), t, c) for t, c in s['top_tags'])
    comm_rows = ''.join('<div class="sr">社区 %s<span class="sv">%s</span></div>' % (k, v) for k, v in s['comm_sizes'])
    pr_rows = ''.join('<div class="sr"><span class="rnk">#%s</span>%s<span class="sv">%.4f</span></div>' %
        (i + 1, l, pr_val) for i, (l, pr_val) in enumerate(s['top_pr']))

    h = HTML_TEMPLATE
    h = h.replace('__VIS_SRC__', vis_src)
    h = h.replace('__DATA_URL__', data_url)
    h = h.replace('__MEM_TOTAL__', str(s['mem_total']))
    h = h.replace('__ENT_TOTAL__', str(s['ent_total']))
    h = h.replace('__EDGE_TOTAL__', str(s['edge_total']))
    h = h.replace('__COMM_TOTAL__', str(s['comm_total']))
    h = h.replace('__HEALTH_SCORE__', str(s['health_score']))
    h = h.replace('__HEALTHY__', str(s['healthy']))
    h = h.replace('__RISK__', str(s['risk']))
    h = h.replace('__LOST__', str(s['lost']))
    h = h.replace('__ENT_ROWS__', ent_rows)
    h = h.replace('__DECAY_ROWS__', decay_rows)
    h = h.replace('__TAG_ROWS__', tag_rows)
    h = h.replace('__COMM_ROWS__', comm_rows)
    h = h.replace('__PR_ROWS__', pr_rows)
    return h


HTML_TEMPLATE = r"""<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>太一记忆图谱 - Mnemos</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;background:#080c18;color:#c9d1d9;overflow:hidden;height:100vh}
#graph{width:100%;height:100vh;position:relative;z-index:1}
/* ===== 顶栏 ===== */
#topbar{position:fixed;top:0;left:0;right:0;height:48px;background:rgba(8,12,24,0.85);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid rgba(163,113,247,0.15);z-index:1000;display:flex;align-items:center;padding:0 14px;gap:10px;box-shadow:0 2px 20px rgba(0,0,0,0.3)}
#topbar h1{font-size:16px;font-weight:700;color:#a371f7;white-space:nowrap;letter-spacing:1px}
.sep{width:1px;height:20px;background:#21262d}
.stat{font-size:11px;color:#8b949e;white-space:nowrap}.stat b{color:#c9d1d9;font-size:13px}
#search{flex:1;max-width:280px;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:5px 12px;color:#c9d1d9;font-size:12px;outline:none}
#search:focus{border-color:#a371f7;box-shadow:0 0 0 2px rgba(163,113,247,0.15)}
.topbtn{background:rgba(0,188,212,0.1);border:1px solid #00BCD4;color:#00BCD4;padding:4px 12px;border-radius:6px;font-size:11px;cursor:pointer;transition:all .15s;white-space:nowrap}
.topbtn:hover{background:rgba(0,188,212,0.2)}
.topbtn.purple{background:rgba(163,113,247,0.1);border-color:#a371f7;color:#a371f7}
.topbtn.purple:hover{background:rgba(163,113,247,0.2)}
.health-dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:4px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
/* ===== 左侧筛选 ===== */
#filters{position:fixed;top:56px;left:14px;z-index:1000;display:flex;flex-direction:column;gap:3px}
#filters button{background:rgba(8,12,24,0.85);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(163,113,247,0.12);color:#8b949e;padding:4px 10px;border-radius:5px;font-size:10px;cursor:pointer;transition:all .2s;text-align:left;white-space:nowrap}
#filters button:hover{border-color:#a371f7;color:#c9d1d9;box-shadow:0 0 8px rgba(163,113,247,0.2)}
#filters button.active{border-color:#a371f7;color:#a371f7;background:rgba(163,113,247,0.1);box-shadow:0 0 12px rgba(163,113,247,0.15)}
/* ===== 右侧信息面板 ===== */
#sidebar{position:fixed;top:48px;right:-360px;bottom:0;width:340px;background:rgba(8,12,24,0.9);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-left:1px solid rgba(163,113,247,0.15);z-index:999;overflow-y:auto;padding:14px;transition:right 0.3s cubic-bezier(0.4,0,0.2,1);box-shadow:-4px 0 20px rgba(0,0,0,0.3)}
#sidebar.open{right:0}
#sidebar h2{font-size:13px;color:#a371f7;margin-bottom:8px;font-weight:600;margin-top:12px}
#sidebar h2:first-child{margin-top:0}
#sidebar .sec{margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #21262d}
.sr{display:flex;align-items:center;gap:6px;font-size:11px;padding:2px 0;color:#8b949e}
.sv{margin-left:auto;color:#c9d1d9;font-variant-numeric:tabular-nums}
.sdot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.rnk{color:#a371f7;font-weight:600;width:22px;font-size:10px}
.tag{display:inline-block;padding:2px 6px;margin:2px;background:#161b22;border:1px solid #30363d;border-radius:10px;font-size:11px;color:#8b949e;cursor:pointer;transition:border-color .15s}
.tag:hover{border-color:#a371f7;color:#c9d1d9}
/* ===== 健康仪表盘 ===== */
.health-bar{width:100%;height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin:4px 0}
.health-fill{height:100%;border-radius:4px;transition:width 0.5s ease}
.health-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:6px 0}
.health-cell{text-align:center;padding:6px;background:#161b22;border-radius:6px;border:1px solid #21262d}
.health-cell .num{font-size:18px;font-weight:700;display:block}
.health-cell .lbl{font-size:9px;color:#8b949e;display:block;margin-top:2px}
/* ===== 节点详情面板 ===== */
#detail{position:fixed;bottom:-300px;left:50%;transform:translateX(-50%);width:520px;max-height:280px;background:rgba(8,12,24,0.92);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(163,113,247,0.2);border-radius:12px 12px 0 0;z-index:1001;overflow-y:auto;padding:16px;display:none;transition:bottom .35s cubic-bezier(0.4,0,0.2,1);box-shadow:0 -4px 30px rgba(0,0,0,0.4),0 0 20px rgba(163,113,247,0.08)}
#detail.show{display:block;bottom:0}
#detail .close{float:right;cursor:pointer;color:#8b949e;font-size:18px;padding:0 4px}
#detail .close:hover{color:#c9d1d9}
#detail .dl{color:#a371f7;font-weight:600;font-size:13px}
#detail .dc{color:#8b949e;margin-top:3px;font-size:11px;word-break:break-all}
#detail .dlinks{margin-top:8px;border-top:1px solid #21262d;padding-top:6px}
#detail .dlinks b{color:#a371f7;font-size:11px}
#detail .dlb{display:inline-block;margin:1px 3px 1px 0;padding:1px 6px;background:#161b22;border:1px solid #30363d;border-radius:4px;font-size:10px;color:#8b949e;cursor:pointer;transition:all .1s}
#detail .dlb:hover{border-color:#a371f7;color:#c9d1d9}
/* ===== 图例 ===== */
#legend{position:fixed;bottom:14px;left:14px;z-index:1000;background:rgba(8,12,24,0.85);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(163,113,247,0.12);border-radius:8px;padding:10px 12px;font-size:10px;min-width:120px}
#legend h3{font-size:11px;color:#a371f7;margin-bottom:5px}
.leg{display:flex;align-items:center;gap:5px;margin:2px 0;color:#8b949e}
.ldot{width:8px;height:8px;border-radius:50%;flex-shrink:0;border:1px solid rgba(255,255,255,0.1);box-shadow:0 0 4px currentColor}
/* ===== 时间线 ===== */
#timeline{position:fixed;bottom:0;left:0;right:0;height:0;overflow:hidden;background:rgba(8,12,24,0.95);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-top:1px solid rgba(163,113,247,0.15);z-index:998;transition:height .3s}
#timeline.open{height:170px}
#timeline canvas{width:100%;height:160px;cursor:crosshair}
/* ===== 加载 ===== */
#loading{position:fixed;inset:0;z-index:2000;display:flex;align-items:center;justify-content:center;background:#080c18;font-size:14px;color:#a371f7}
@keyframes breathe{0%,100%{opacity:.5}50%{opacity:1}}
#loading .spin{animation:breathe 1.5s ease infinite}
/* ===== 快捷键提示 ===== */
#kbd-hint{position:fixed;bottom:50px;left:50%;transform:translateX(-50%);background:rgba(8,12,24,0.95);border:1px solid #21262d;border-radius:8px;padding:8px 16px;font-size:11px;color:#8b949e;z-index:1002;display:none}
kbd{background:#161b22;border:1px solid #30363d;border-radius:3px;padding:1px 5px;font-size:10px;color:#c9d1d9}
</style>
</head><body>
<div id="loading"><div class="spin">🔮 正在加载记忆图谱...</div></div>

<div id="topbar">
<h1>🔮 太一记忆图谱</h1><div class="sep"></div>
<div class="stat">记忆 <b>__MEM_TOTAL__</b></div><div class="sep"></div>
<div class="stat">实体 <b>__ENT_TOTAL__</b></div><div class="sep"></div>
<div class="stat">连接 <b>__EDGE_TOTAL__</b></div><div class="sep"></div>
<div class="stat">社区 <b>__COMM_TOTAL__</b></div><div class="sep"></div>
<div class="stat"><span class="health-dot" style="background:#66BB6A"></span>健康 <b>__HEALTH_SCORE__%</b></div>
<input type="text" id="search" placeholder="搜索记忆/实体 (Ctrl+K)" oninput="searchNodes(this.value)">
<button class="topbtn" onclick="expandAll()">全部展开</button>
<button class="topbtn purple" onclick="toggleSidebar()">📊 统计</button>
<button class="topbtn" onclick="toggleTimeline()">📅 时间线</button>
<button class="topbtn purple" onclick="showKbdHint()">⌨️ 快捷键</button>
<button class="topbtn" onclick="zoomFit()">适应</button>
</div>

<div id="filters">
<button class="active" onclick="applyFilter('all',this)">全部</button>
<button onclick="applyFilter('comm',this)">🏘️ 社区</button>
<button onclick="applyFilter('entity',this)">📦 实体</button>
<button onclick="applyFilter('memory',this)">🧠 记忆</button>
<button onclick="applyFilter('core',this)">🟠 核心</button>
<button onclick="applyFilter('belief',this)">🔴 信念</button>
<button onclick="applyFilter('context',this)">🟢 上下文</button>
<button onclick="applyFilter('impression',this)">🔵 印象</button>
</div>

<div id="graph"></div>

<div id="sidebar">
<h2>📊 健康度</h2>
<div class="sec">
<div class="health-bar"><div class="health-fill" style="width:__HEALTH_SCORE__%;background:linear-gradient(90deg,#EF5350,#FFA726,#66BB6A)"></div></div>
<div class="health-grid">
<div class="health-cell"><span class="num" style="color:#66BB6A">__HEALTHY__</span><span class="lbl">健康</span></div>
<div class="health-cell"><span class="num" style="color:#FFA726">__RISK__</span><span class="lbl">风险</span></div>
<div class="health-cell"><span class="num" style="color:#EF5350">__LOST__</span><span class="lbl">遗忘</span></div>
</div>
</div>
<h2>🏷️ 实体分布</h2><div class="sec">__ENT_ROWS__</div>
<h2>⏰ 衰减分布</h2><div class="sec">__DECAY_ROWS__</div>
<h2>📌 热门标签</h2><div class="sec">__TAG_ROWS__</div>
<h2>🏘️ 社区规模</h2><div class="sec">__COMM_ROWS__</div>
<h2>🏆 PageRank Top10</h2><div class="sec">__PR_ROWS__</div>
</div>

<div id="legend">
<h3>图例</h3>
<div class="leg"><span class="ldot" style="background:#a371f7;color:#a371f7"></span>社区</div>
<div class="leg"><span class="ldot" style="background:#4FC3F7;color:#4FC3F7"></span>印象</div>
<div class="leg"><span class="ldot" style="background:#66BB6A;color:#66BB6A"></span>上下文</div>
<div class="leg"><span class="ldot" style="background:#FFA726;color:#FFA726"></span>核心</div>
<div class="leg"><span class="ldot" style="background:#EF5350;color:#EF5350"></span>信念</div>
<div class="leg"><span class="ldot" style="background:#78909C;color:#78909C"></span>实体</div>
</div>

<div id="detail"></div>

<div id="timeline"><canvas id="timelineCanvas"></canvas></div>

<div id="kbd-hint">
<kbd>Ctrl+K</kbd> 搜索 &nbsp;
<kbd>↑↓</kbd> 遍历 &nbsp;
<kbd>Enter</kbd> 展开 &nbsp;
<kbd>T</kbd> 时间线 &nbsp;
<kbd>S</kbd> 统计 &nbsp;
<kbd>F</kbd> 适应视图 &nbsp;
<kbd>1-4</kbd> 按分层筛选
</div>
<script src="__VIS_SRC__"></script>
<script>
// ===== 常量 =====
var ND = [], ED = [], chart = null;
var TIER_COL = {'impression':'#4FC3F7','context':'#66BB6A','core':'#FFA726','belief':'#EF5350'};
var TIER_CN = {'impression':'印象','context':'上下文','core':'核心','belief':'信念'};
var ENT_CN = {'concept':'概念','person':'人物','project':'项目','technology':'技术','location':'地点','':'其他'};
var ENT_COL = {'concept':'#CE93D8','person':'#FF8A65','project':'#4DB6AC','technology':'#90A4AE','location':'#AED581','':'#78909C'};

// ===== 颜色工具 =====
function tierColor(n){
  if(n.group==='community') return '#a371f7';
  if(n.group==='entity') return ENT_COL[n.etype]||'#78909C';
  return TIER_COL[n.tier]||'#4FC3F7';
}

// ===== 社区展开状态 =====
var expandedCommunities = {};
var allNodesOriginal = [];

// ===== 初始化 echarts =====
function initGraph(){
  var container = document.getElementById('graph');
  chart = echarts.init(container, null, {renderer:'canvas'});

  // 记录原始节点数据
  allNodesOriginal = ND.slice();

  updateGraph();
  document.getElementById('loading').style.display='none';
}

// ===== 构建 echarts 图数据 =====
function buildGraphData(filter){
  // 决定哪些节点可见
  var visibleIds = {};
  var nodesData = [];

  for(var i=0; i<ND.length; i++){
    var n = ND[i];
    var show = false;
    if(!filter || filter==='all') show = true;
    else if(filter==='comm') show = (n.group==='community');
    else if(filter==='entity') show = (n.group==='entity' || n.group==='community');
    else if(filter==='memory') show = (n.group==='memory');
    else if(filter==='core'||filter==='belief'||filter==='context'||filter==='impression') show = (n.tier===filter || n.group==='community' || n.group==='entity');

    // 社区成员展开检查
    if(n.group==='entity' && n.community>=0 && !expandedCommunities[n.community]) show = false;

    if(!show) continue;
    visibleIds[n.id] = true;

    var pr = n.pageRank || 0;
    var sz, zLevel;
    if(n.group==='community'){
      sz = 20 + Math.min(pr*1200, 60);
      zLevel = 10;
    } else if(n.group==='entity'){
      sz = 10 + Math.min(pr*600, 20);
      zLevel = 5;
    } else {
      sz = 4 + Math.min(pr*400, 12) + (n.decay||0)*6;
      zLevel = 3;
    }

    var col = tierColor(n);
    nodesData.push({
      id: n.id,
      name: n.label || '',
      symbolSize: sz,
      category: n.group,
      itemStyle: {
        color: col,
        shadowBlur: n.group==='community' ? 25 : (n.group==='entity' ? 12 : 6),
        shadowColor: col,
        borderColor: 'rgba(255,255,255,0.15)',
        borderWidth: n.group==='community' ? 2 : 0.5
      },
      label: {
        show: n.group==='community' || pr > 0.008,
        color: '#e0e0e0',
        fontSize: n.group==='community' ? 14 : 11,
        fontWeight: n.group==='community' ? 'bold' : 'normal',
        formatter: n.label || '',
        position: 'bottom',
        distance: 5
      },
      // Store raw data for tooltip/detail
      raw: n,
      zLevel: zLevel
    });
  }

  // Build links
  var linksData = [];
  for(var i=0; i<ED.length; i++){
    var e = ED[i];
    if(visibleIds[e.from_] && visibleIds[e.to]){
      linksData.push({
        source: e.from_,
        target: e.to,
        lineStyle: {
          color: 'rgba(163,113,247,0.3)',
          width: 1.5,
          curveness: 0.2
        }
      });
    }
  }

  return {nodes: nodesData, links: linksData};
}

// ===== 更新图表 =====
var currentFilter = 'all';
function updateGraph(){
  var data = buildGraphData(currentFilter);
  var categories = [
    {name:'community', itemStyle:{color:'#a371f7'}},
    {name:'entity', itemStyle:{color:'#78909C'}},
    {name:'memory', itemStyle:{color:'#4FC3F7'}}
  ];

  var option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(8,12,24,0.95)',
      borderColor: 'rgba(163,113,247,0.3)',
      borderWidth: 1,
      textStyle: {color: '#c9d1d9', fontSize: 12},
      formatter: function(p){
        if(p.dataType==='edge') return '';
        var d = p.data.raw;
        if(!d) return p.name;
        var html = '<b style="color:#a371f7">'+(d.label||d.id)+'</b><br>';
        if(d.group==='community') html += '🏘️ 社区 '+d.community+'<br>实体: '+(d.entity_count||0)+' | 记忆: '+(d.memory_count||0);
        else if(d.group==='entity') html += '📦 '+(ENT_CN[d.etype]||d.etype||'实体')+'<br>记忆: '+(d.mem_cnt||0)+' | 提及: '+(d.mention_cnt||0);
        else html += (TIER_CN[d.tier]||d.tier)+' | 衰减: '+(d.decay||0).toFixed(3)+' | 检索: '+(d.hits||0)+'次<br>'+((d.content||'').substring(0,80));
        return html;
      }
    },
    series: [{
      type: 'graph',
      layout: 'force',
      animation: true,
      animationDuration: 1500,
      animationEasingUpdate: 'quinticInOut',
      roam: true,
      zoom: 0.8,
      scaleLimit: {min: 0.1, max: 10},
      force: {
        repulsion: 300,
        gravity: 0.1,
        edgeLength: [80, 300],
        friction: 0.6,
        layoutAnimation: true
      },
      categories: categories,
      data: data.nodes,
      links: data.links,
      lineStyle: {
        opacity: 0.6,
        width: 1.5,
        curveness: 0.2,
        color: 'rgba(163,113,247,0.35)'
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: {width: 3, color: '#a371f7'},
        itemStyle: {shadowBlur: 30, shadowColor: '#a371f7'}
      },
      blur: {
        itemStyle: {opacity: 0.15},
        lineStyle: {opacity: 0.05}
      },
      edgeSymbol: ['none', 'none'],
      selectedMode: 'single',
      select: {
        itemStyle: {shadowBlur: 40, shadowColor: '#a371f7'},
        lineStyle: {width: 3, color: '#a371f7'}
      }
    }]
  };

  chart.setOption(option, true);

  // 点击事件
  chart.off('click');
  chart.on('click', function(params){
    if(params.dataType==='node' && params.data && params.data.raw){
      showDetail(params.data.raw);
    }
  });

  // 双击展开社区
  chart.off('dblclick');
  chart.on('dblclick', function(params){
    if(params.dataType==='node' && params.data && params.data.raw){
      var d = params.data.raw;
      if(d.group==='community'){
        if(expandedCommunities[d.community]) delete expandedCommunities[d.community];
        else expandedCommunities[d.community] = true;
        updateGraph();
        if(window._particleEmit){
          var rect = document.getElementById('graph').getBoundingClientRect();
          window._particleEmit(params.event.offsetX || rect.width/2, params.event.offsetY || rect.height/2, '#a371f7', 30);
        }
      }
    }
  });
}

// ===== 详情面板 =====
function showDetail(n){
  var d = document.getElementById('detail');
  var h = '<span class="close" onclick="this.parentElement.classList.remove(\'show\')">&#10005;</span>';
  if(n.group==='community'){
    h += '<div class="dl">🏘️ 社区 '+n.community+'</div><div class="dc">'+n.entity_count+' 个实体 | '+n.memory_count+' 条记忆</div>';
    var kids = allNodesOriginal.filter(function(x){return x.community===n.community && x.group!=='community'});
    if(kids.length) h += '<div class="dlinks"><b>成员 ('+kids.length+')</b><br>'+kids.slice(0,30).map(function(x){return x.label}).join(' · ')+'</div>';
  } else if(n.group==='memory'){
    h += '<div class="dl">'+(n.title?n.title.split('<br>')[0].replace(/<[^>]+>/g,''):'')+'</div>';
    h += '<div class="dc">分层: '+(TIER_CN[n.tier]||n.tier)+' | 衰减: '+(n.decay||0).toFixed(3)+' | 检索: '+(n.hits||0)+'次</div>';
    h += '<div class="dc">'+((n.content||'').substring(0,280))+'</div>';
  } else {
    h += '<div class="dl">'+n.label+'</div>';
    h += '<div class="dc">类型: '+(ENT_CN[n.etype]||n.etype||'其他')+' | 记忆: '+(n.mem_cnt||0)+' 条 | 提及: '+(n.mention_cnt||0)+'次</div>';
    h += '<div class="dc">PageRank: '+(n.pageRank||0).toFixed(4)+' | 社区: '+(n.community>=0?n.community:'无')+'</div>';
  }
  d.innerHTML = h; d.classList.add('show');
}

// ===== 搜索 =====
function searchNodes(q){
  if(!q){updateGraph(); return}
  var ql = q.toLowerCase();
  // Highlight matching nodes
  chart.dispatchAction({type:'downplay'});
  for(var i=0;i<ND.length;i++){
    var n = ND[i];
    var m = (n.label||'').toLowerCase().indexOf(ql)>=0 ||
            (n.content||'').toLowerCase().indexOf(ql)>=0;
    if(m) chart.dispatchAction({type:'highlight', dataIndex: i});
  }
  document.getElementById('search').style.borderColor = '#66BB6A';
}

// ===== 筛选 =====
function applyFilter(g, btn){
  document.querySelectorAll('#filters button').forEach(function(b){b.classList.remove('active')});
  if(btn) btn.classList.add('active');
  currentFilter = g;
  expandedCommunities = {};
  updateGraph();
}

function expandAll(){
  var btn = document.querySelector('.topbtn');
  var allExpanded = Object.keys(expandedCommunities).length > 0;
  if(allExpanded){
    expandedCommunities = {};
    btn.textContent = '全部展开';
  } else {
    for(var i=0;i<ND.length;i++){
      if(ND[i].group==='community') expandedCommunities[ND[i].community] = true;
    }
    btn.textContent = '全部收起';
  }
  updateGraph();
}
function zoomFit(){ chart.dispatchAction({type:'restore'}); }
function toggleSidebar(){ document.getElementById('sidebar').classList.toggle('open'); }

// ===== 时间线 =====
var timelineOpen = false;
function toggleTimeline(){
  timelineOpen = !timelineOpen;
  var el = document.getElementById('timeline');
  if(timelineOpen){el.classList.add('open');drawTimeline()}
  else el.classList.remove('open');
}
function drawTimeline(){
  var canvas = document.getElementById('timelineCanvas');
  var ctx = canvas.getContext('2d');
  var W = canvas.parentElement.clientWidth;
  canvas.width = W; canvas.height = 160;
  ctx.fillStyle = '#0d1117'; ctx.fillRect(0,0,W,160);
  var mems = [];
  for(var i=0;i<ND.length;i++){
    var n = ND[i];
    if(n.group!=='memory'||!n.created) continue;
    var d = new Date(n.created);
    if(isNaN(d.getTime())) continue;
    mems.push({x:d.getTime(),tier:n.tier,decay:n.decay||0,label:n.label,id:n.id});
  }
  if(!mems.length){ctx.fillStyle='#8b949e';ctx.font='12px sans-serif';ctx.fillText('暂无带时间戳的记忆',W/2-60,80);return}
  mems.sort(function(a,b){return a.x-b.x});
  var minX=mems[0].x, maxX=mems[mems.length-1].x;
  if(maxX===minX)maxX=minX+1;
  var pad=40;
  ctx.strokeStyle='#21262d';ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(pad,140);ctx.lineTo(W-pad,140);ctx.stroke();
  ctx.fillStyle='#8b949e';ctx.font='9px sans-serif';ctx.textAlign='center';
  var nTicks=Math.min(8,mems.length);
  for(var i=0;i<nTicks;i++){
    var tx=pad+(W-2*pad)*i/(nTicks-1);
    var t=new Date(minX+(maxX-minX)*i/(nTicks-1));
    ctx.fillText((t.getMonth()+1)+'/'+t.getDate(),tx,155);
    ctx.strokeStyle='#161b22';ctx.beginPath();ctx.moveTo(tx,5);ctx.lineTo(tx,140);ctx.stroke();
  }
  var tierY={'impression':115,'context':90,'core':65,'belief':40};
  for(var i=0;i<mems.length;i++){
    var m=mems[i];
    var px=pad+(W-2*pad)*(m.x-minX)/(maxX-minX);
    var py=tierY[m.tier]||95;
    var r=3+m.decay*5;
    ctx.globalAlpha=0.3+m.decay*0.7;
    ctx.fillStyle=TIER_COL[m.tier]||'#90CAF9';
    ctx.beginPath();ctx.arc(px,py,r,0,Math.PI*2);ctx.fill();
    ctx.globalAlpha=1;
  }
  ctx.font='9px sans-serif';ctx.textAlign='left';
  Object.keys(tierY).forEach(function(t){
    ctx.fillStyle=TIER_COL[t]||'#90CAF9';
    ctx.fillText(TIER_CN[t]||t,2,tierY[t]+3);
  });
}

// ===== 快捷键 =====
function showKbdHint(){
  var el=document.getElementById('kbd-hint');
  el.style.display=el.style.display==='block'?'none':'block';
  setTimeout(function(){el.style.display='none'},5000);
}
document.addEventListener('keydown',function(e){
  if(e.target.tagName==='INPUT')return;
  if(e.key==='k'&&(e.ctrlKey||e.metaKey)){e.preventDefault();document.getElementById('search').focus();}
  else if(e.key==='Escape'){document.getElementById('detail').classList.remove('show');document.getElementById('kbd-hint').style.display='none';}
  else if(e.key==='t'||e.key==='T')toggleTimeline();
  else if(e.key==='s'||e.key==='S')toggleSidebar();
  else if(e.key==='f'||e.key==='F')zoomFit();
  else if(e.key==='1')applyFilter('impression',null);
  else if(e.key==='2')applyFilter('context',null);
  else if(e.key==='3')applyFilter('core',null);
  else if(e.key==='4')applyFilter('belief',null);
  else if(e.key==='0')applyFilter('all',null);
});

// ===== 窗口resize =====
window.addEventListener('resize',function(){if(chart)chart.resize()});

// ===== 异步加载数据 =====
fetch('__DATA_URL__').then(function(r){return r.json()}).then(function(d){ND=d.nodes;ED=d.edges;initGraph()}).catch(function(e){document.getElementById('loading').innerHTML='<span style="color:#EF5350">❌ 加载失败: '+e.message+'</span>'});
</script></body></html>"""


def gen_json_data():
    """返回 {nodes, edges, stats} JSON 供 API 端点使用。"""
    imp, ent, edg, pr, cm = load()
    nodes, edges = build(imp, ent, edg, pr, cm)
    s = stats_summary(imp, ent, edg, pr, cm)
    return {"nodes": nodes, "edges": edges, "stats": s}


def main():
    ap = argparse.ArgumentParser(description='Mnemos 记忆图谱可视化 v5.0 (ECharts)')
    ap.add_argument('--no-open', action='store_true', help='不打开浏览器')
    ap.add_argument('--output', default=OUT, help='输出HTML路径')
    ap.add_argument('--serve', action='store_true', help='启动HTTP服务器(端口9730)')
    ap.add_argument('--verbose', action='store_true', help='详细输出')
    args = ap.parse_args()
    global VERBOSE; VERBOSE = args.verbose

    imp, ent, edg, pr, cm = load()
    if VERBOSE: print("正在构建图谱...")
    nodes, edges = build(imp, ent, edg, pr, cm)
    s = stats_summary(imp, ent, edg, pr, cm)
    html = gen_html(nodes, edges, s)

    # 写入 memory_viz.html
    out_path = os.path.expanduser(args.output)
    with open(out_path, 'w', encoding='utf-8') as f: f.write(html)
    sz = os.path.getsize(out_path)
    print(f"✅ 生成: {out_path} ({sz // 1024}KB)")
    print(f"📊 统计: {s['mem_total']} 记忆 | {s['ent_total']} 实体 | {s['edge_total']} 边 | {s['comm_total']} 社区")
    print(f"🏥 健康度: {s['health_score']}% (健康{s['healthy']} / 风险{s['risk']} / 遗忘{s['lost']})")

    if args.serve:
        # 为 standalone 模式生成 JSON 数据文件
        jdata = gen_json_data()
        jpath = os.path.join(os.path.dirname(out_path), 'memory_viz.json')
        import json
        with open(jpath, 'w', encoding='utf-8') as f:
            json.dump(jdata, f, ensure_ascii=False)
        print(f"📦 数据: {jpath}")
        # 生成 standalone 适用的 HTML
        html_standalone = gen_html(nodes, edges, s, vis_src='echarts.min.js', data_url='memory_viz.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html_standalone)
        sz = os.path.getsize(out_path)
        print(f"✅ Standalone HTML: {out_path} ({sz // 1024}KB)")

        port = 9730
        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=os.path.dirname(args.output), **kw)
            def log_message(self, *a): pass
        print(f"🌐 服务: http://localhost:{port}/memory_viz.html")
        socketserver.TCPServer.allow_reuse_address = True
        srv = socketserver.TCPServer(("0.0.0.0", port), H)
        webbrowser.open(f"http://localhost:{port}/memory_viz.html")
        srv.serve_forever()
    elif not args.no_open:
        webbrowser.open(f"file://{os.path.abspath(args.output)}")


if __name__ == '__main__':
    main()
