#!/usr/bin/env python3
"""
Mnemos 可视化仪表盘服务器

启动后打开浏览器访问 http://localhost:8765
即可看到 3D 记忆星系、信念演化树、实体图谱、统计面板。

依赖: pip install mnemos  (或本地 pip install -e .)
"""

from __future__ import annotations

import json
import argparse
import http.server
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.viz.data_provider import DashboardProvider

HERE = Path(__file__).parent


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    store: PalimpsestStore | None = None
    provider: DashboardProvider | None = None

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/galaxy":
            self._json(self.provider.galaxy())
        elif parsed.path == "/api/belief-tree":
            qs = parse_qs(parsed.query)
            mid = qs.get("memory_id", [None])[0]
            self._json(self.provider.belief_tree(mid))
        elif parsed.path == "/api/entity-graph":
            qs = parse_qs(parsed.query)
            center = qs.get("center", [None])[0]
            self._json(self.provider.entity_graph(center))
        elif parsed.path == "/api/overview":
            self._json(self.provider.overview())
        elif parsed.path == "/" or parsed.path == "":
            self._serve_dashboard()
        else:
            super().do_GET()

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_dashboard(self):
        html = _DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, format, *args):
        pass  # 静默模式


_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mnemos — 独立记忆世界</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0a1a;color:#e0e0f0;overflow:hidden}
#galaxy{position:fixed;inset:0;z-index:0}
#hud{position:fixed;inset:0;z-index:10;pointer-events:none;display:flex;flex-direction:column}
#hud>*{pointer-events:auto}
#header{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;background:linear-gradient(180deg,rgba(10,10,26,.95) 60%,transparent)}
#header h1{font-size:28px;font-weight:300;letter-spacing:4px;background:linear-gradient(135deg,#a78bfa,#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
#header .subtitle{font-size:12px;color:#6366f1;margin-top:2px}
#panels{display:flex;gap:12px;padding:0 24px 24px;flex:1;overflow:hidden}
.panel{flex:1;min-width:0;background:rgba(16,16,42,.85);backdrop-filter:blur(12px);border:1px solid rgba(99,102,241,.2);border-radius:16px;padding:16px;overflow-y:auto;max-height:calc(100vh - 120px)}
.panel h3{font-size:14px;font-weight:600;color:#818cf8;margin-bottom:12px;text-transform:uppercase;letter-spacing:1px}
.stat-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(99,102,241,.1);font-size:13px}
.stat-row .val{color:#a78bfa;font-weight:600}
.belief-item{padding:8px 12px;margin:6px 0;background:rgba(99,102,241,.08);border-radius:8px;border-left:3px solid #818cf8;font-size:12px;line-height:1.5}
.belief-item.superseded{border-left-color:#ef4444;opacity:.6;text-decoration:line-through}
.belief-item .conf{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;margin-left:6px}
.conf-speculative{background:rgba(239,68,68,.2);color:#fca5a5}
.conf-tentative{background:rgba(251,191,36,.2);color:#fde68a}
.conf-confirmed{background:rgba(34,197,94,.2);color:#86efac}
.conf-bedrock{background:rgba(99,102,241,.3);color:#c4b5fd}
.ent-node{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;margin:3px;background:rgba(99,102,241,.12);border-radius:12px;font-size:12px;cursor:pointer;transition:all .2s}
.ent-node:hover{background:rgba(99,102,241,.3);transform:scale(1.05)}
.timeline-bar{display:flex;align-items:flex-end;gap:2px;height:80px;margin:12px 0}
.timeline-bar .bar{flex:1;min-width:2px;border-radius:2px 2px 0 0;transition:all .3s;cursor:pointer}
.timeline-bar .bar:hover{opacity:.8;transform:scaleY(1.1)}
#tooltip{position:fixed;z-index:100;padding:8px 12px;background:rgba(16,16,42,.95);border:1px solid rgba(99,102,241,.3);border-radius:8px;font-size:12px;pointer-events:none;display:none;max-width:280px}
</style>
</head>
<body>
<div id="galaxy"></div>
<div id="hud">
  <div id="header">
    <div><h1>MNEMOS</h1><div class="subtitle">独立记忆世界 · 记忆可视化仪表盘</div></div>
    <div style="text-align:right;font-size:12px;color:#6366f1">
      <div id="live-stats">加载中…</div>
    </div>
  </div>
  <div id="panels">
    <div class="panel" id="panel-stats">
      <h3>📊 统计概览</h3>
      <div id="stats-content">加载中…</div>
      <h3 style="margin-top:16px">⏳ 时间线</h3>
      <div class="timeline-bar" id="timeline-bar"></div>
    </div>
    <div class="panel" id="panel-beliefs">
      <h3>🌳 信念演化</h3>
      <div id="beliefs-content">点击星体查看信念链</div>
    </div>
    <div class="panel" id="panel-entities">
      <h3>🕸️ 实体图谱</h3>
      <div id="entities-content">加载中…</div>
    </div>
  </div>
</div>
<div id="tooltip"></div>

<script type="importmap">
{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js","three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';

// ── 场景初始化 ──────────────────────────────────
const W = window.innerWidth, H = window.innerHeight;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(60, W/H, 0.1, 1000);
camera.position.set(0, 8, 25);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
renderer.setSize(W, H);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.getElementById('galaxy').appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 5;
controls.maxDistance = 60;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.3;

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(W, H), 0.6, 0.4, 0.85);
bloom.threshold = 0.1;
bloom.strength = 1.2;
bloom.radius = 0.8;
composer.addPass(bloom);

// ── 背景星空 ────────────────────────────────────
const starsGeo = new THREE.BufferGeometry();
const starsCount = 2000;
const starsPos = new Float32Array(starsCount * 3);
for(let i=0;i<starsCount*3;i++) starsPos[i] = (Math.random() - 0.5) * 60;
starsGeo.setAttribute('position', new THREE.BufferAttribute(starsPos, 3));
const starsMat = new THREE.PointsMaterial({color:0x6366f1, size:0.03, transparent:true, blending:THREE.AdditiveBlending});
const stars = new THREE.Points(starsGeo, starsMat);
scene.add(stars);

// ── 星体材质池 ──────────────────────────────────
const tierColors = {impression:0x60a5fa, pattern:0xa78bfa, principle:0xfbbf24};
const tierGlows = {impression:0x3b82f6, pattern:0x8b5cf6, principle:0xf59e0b};
const nodeMeshes = new Map();
const linkLines = [];
let galaxyData = null;

function createStarNode(node) {
  const color = tierColors[node.tier] || 0x60a5fa;
  const size = node.tier === 'principle' ? 0.25 : node.tier === 'pattern' ? 0.18 : 0.1;
  const geo = new THREE.SphereGeometry(size, 16, 16);
  const mat = new THREE.MeshStandardMaterial({color, emissive:color, emissiveIntensity:0.6, roughness:0.3});
  const mesh = new THREE.Mesh(geo, mat);
  mesh.userData = node;
  return mesh;
}

function createLink(source, target) {
  const points = [source.position.clone(), target.position.clone()];
  const geo = new THREE.BufferGeometry().setFromPoints(points);
  const mat = new THREE.LineBasicMaterial({color:0x6366f1, transparent:true, opacity:0.15, blending:THREE.AdditiveBlending});
  return new THREE.Line(geo, mat);
}

// ── 加载星系数据 ────────────────────────────────
async function loadGalaxy() {
  const res = await fetch('/api/galaxy');
  galaxyData = await res.json();
  const nodes = galaxyData.nodes;
  if(!nodes.length) return;

  // 清除旧数据
  nodeMeshes.forEach(m => scene.remove(m));
  nodeMeshes.clear();
  linkLines.forEach(l => scene.remove(l));
  linkLines.length = 0;

  // 螺旋布局
  const total = nodes.length;
  nodes.forEach((n, i) => {
    const t = i / total;
    const angle = t * Math.PI * 8; // 4 圈螺旋
    const radius = 3 + t * 14;
    const height = (Math.random() - 0.5) * (8 - t * 6);
    const x = Math.cos(angle) * radius;
    const z = Math.sin(angle) * radius;
    n._x = x; n._y = height; n._z = z;
  });

  // 创建节点
  nodes.forEach(n => {
    const mesh = createStarNode(n);
    mesh.position.set(n._x, n._y, n._z);
    scene.add(mesh);
    nodeMeshes.set(n.id, mesh);
  });

  // 创建连线
  galaxyData.links.forEach(l => {
    const sm = nodeMeshes.get(l.source);
    const tm = nodeMeshes.get(l.target);
    if(sm && tm) {
      const line = createLink(sm, tm);
      scene.add(line);
      linkLines.push({line, source:l.source, target:l.target});
    }
  });

  // 光源
  const ambient = new THREE.AmbientLight(0x333366, 0.5);
  scene.add(ambient);
  const point = new THREE.PointLight(0x818cf8, 2, 40);
  point.position.set(0, 5, 0);
  scene.add(point);

  updateStats();
}

// ── 统计面板 ────────────────────────────────────
async function updateStats() {
  const res = await fetch('/api/overview');
  const data = await res.json();
  const c = data.counts;
  document.getElementById('stats-content').innerHTML = `
    <div class="stat-row"><span>印象 (Impressions)</span><span class="val">${c.impressions}</span></div>
    <div class="stat-row"><span>模式 (Patterns)</span><span class="val">${c.patterns}</span></div>
    <div class="stat-row"><span>原则 (Principles)</span><span class="val">${c.principles}</span></div>
    <div class="stat-row"><span>实体</span><span class="val">${c.entities}</span></div>
    <div class="stat-row"><span>实体关联</span><span class="val">${c.cooccur_pairs}</span></div>
    <div class="stat-row"><span>信念记录</span><span class="val">${c.beliefs}</span></div>
  `;

  document.getElementById('live-stats').innerHTML = `
    总记忆 ${c.impressions + c.patterns + c.principles} · 实体 ${c.entities}
  `;

  // 时间线
  const tl = document.getElementById('timeline-bar');
  tl.innerHTML = '';
  const maxCount = Math.max(...data.timeline.map(t=>t.count), 1);
  data.timeline.forEach(t => {
    const bar = document.createElement('div');
    bar.className = 'bar';
    bar.style.height = (t.count / maxCount * 70 + 4) + 'px';
    bar.style.background = `linear-gradient(180deg, #818cf8, #6366f1)`;
    bar.title = `${t.date}: ${t.count} 条记忆`;
    tl.appendChild(bar);
  });

  // 实体图谱
  const egRes = await fetch('/api/entity-graph');
  const eg = await egRes.json();
  const ec = document.getElementById('entities-content');
  ec.innerHTML = eg.nodes.slice(0, 30).map(n =>
    `<span class="ent-node" onclick="clickEntity('${n.label}')" title="${n.type} · ${n.memory_count}条记忆">${n.label}</span>`
  ).join('');
}

// ── 点击星体查看信念 ────────────────────────────
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
window.addEventListener('click', async (e) => {
  if(e.target.closest('.panel')) return;
  mouse.x = (e.clientX / W) * 2 - 1;
  mouse.y = -(e.clientY / H) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects([...nodeMeshes.values()]);
  if(hits.length) {
    const node = hits[0].object.userData;
    showBeliefTree(node);
  }
});

async function showBeliefTree(node) {
  const res = await fetch('/api/belief-tree?memory_id=' + node.id);
  const data = await res.json();
  const bc = document.getElementById('beliefs-content');
  if(!data.trees.length) {
    bc.innerHTML = `<div style="color:#6366f1;font-size:13px">📌 已选中: ${node.label}<br>该记忆暂无信念记录</div>`;
    return;
  }
  const tree = data.trees[0];
  bc.innerHTML = `<div style="font-size:13px;margin-bottom:8px;color:#a78bfa">📌 ${tree.title}</div>` +
    tree.chain.map(b => `
      <div class="belief-item${b.is_active ? '' : ' superseded'}">
        ${b.content}
        <span class="conf conf-${b.confidence}">${b.confidence}</span>
        <div style="font-size:10px;color:#6366f1;margin-top:4px">
          ${b.adopted_at?.slice(0,10)} · ${b.source || '未知来源'}
          ${b.superseded_by ? ' → 已被修正' : b.is_active ? ' ✅ 当前有效' : ''}
        </div>
      </div>
    `).join('');
}

window.clickEntity = async (label) => {
  const res = await fetch('/api/entity-graph?center=' + label);
  const data = await res.json();
  const ec = document.getElementById('entities-content');
  ec.innerHTML = `<div style="font-size:13px;color:#a78bfa;margin-bottom:8px">🔗 与 "${label}" 关联的实体:</div>` +
    data.edges.map(e => {
      const other = e.source === label ? e.target : e.source;
      return `<span class="ent-node" onclick="clickEntity('${other}')">${other} <span style="color:#6366f1;font-size:10px">×${e.weight}</span></span>`;
    }).join('');
};

// ── 动画循环 ────────────────────────────────────
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();

  // 星体微动
  nodeMeshes.forEach((mesh, id) => {
    const n = mesh.userData;
    mesh.position.y = n._y + Math.sin(t * 1.5 + n._x) * 0.15;
    mesh.rotation.y += 0.003;
    mesh.material.emissiveIntensity = 0.4 + Math.sin(t * 2 + n._z) * 0.2;
  });

  // 连线更新
  linkLines.forEach(({line, source, target}) => {
    const sm = nodeMeshes.get(source);
    const tm = nodeMeshes.get(target);
    if(sm && tm) {
      const positions = line.geometry.attributes.position;
      positions.setXYZ(0, sm.position.x, sm.position.y, sm.position.z);
      positions.setXYZ(1, tm.position.x, tm.position.y, tm.position.z);
      positions.needsUpdate = true;
    }
  });

  // 星空旋转
  stars.rotation.y += 0.0002;
  stars.rotation.x += 0.0001;

  controls.update();
  composer.render();
}

// ── 启动 ────────────────────────────────────────
loadGalaxy().then(() => animate());
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Mnemos 可视化仪表盘")
    parser.add_argument("--db", default="memory.db", help="数据库路径")
    parser.add_argument("--port", type=int, default=8765, help="HTTP 端口")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    args = parser.parse_args()

    store = PalimpsestStore(args.db)
    store.connect()

    DashboardHandler.store = store
    DashboardHandler.provider = DashboardProvider(store)

    server = http.server.HTTPServer((args.host, args.port), DashboardHandler)
    print("\n  🌌 Mnemos 记忆星系仪表盘已启动")
    print(f"  📡 http://localhost:{args.port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  再见 👋")
        store.close()


if __name__ == "__main__":
    main()
