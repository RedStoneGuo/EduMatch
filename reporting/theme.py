# -*- coding: utf-8 -*-
"""EduMatch 报告页面主题（CSS/JS 唯一来源）。

`EduMatch-演示页面/_build/build_page.py` 与 `reporting/render.py` 都从这里取，
保证任意院校/专业生成的分析报告与既有演示页面是同一套版式。
"""

CSS = r"""
:root{
  --paper:#f4f1ea; --ink:#141414; --dim:#6b6659; --line:#dcd6c8;
  --red:#d8342a; --clay:#c9a227; --rule:#141414;
  --serif:"Songti SC","SimSun",Georgia,serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  background:var(--paper);color:var(--ink);
  font-family:"PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;
  line-height:1.7;-webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px;margin:0 auto;padding:0 30px}
h1,h2,h3{letter-spacing:-.02em}
a{color:inherit;text-decoration:none}
.num{font-variant-numeric:tabular-nums}

/* ---------- 顶部导航（粘性，可点击跳转） ---------- */
.scalenav{
  position:sticky;top:0;z-index:50;background:rgba(244,241,234,.94);
  backdrop-filter:saturate(1.2) blur(8px);border-bottom:3px solid var(--ink);
}
.scalenav .in{max-width:1180px;margin:0 auto;padding:0 30px;display:flex;align-items:stretch;gap:0}
.sn-brand{font-weight:900;letter-spacing:.08em;font-size:14px;padding:11px 16px 11px 0;display:flex;align-items:center}
.sn-brand b{color:var(--red)}
.sn-links{display:flex;flex:1;justify-content:flex-end}
.sn-links a{
  padding:8px 12px;border-left:1px solid var(--line);display:flex;flex-direction:column;gap:1px;min-width:92px;
  transition:background .15s;
}
/* 顶栏必须**固定单行**：副标题再长也只占一行、超出省略号，绝不允许换行把顶栏顶高 */
.sn-links a b{font-size:14px;font-weight:800;letter-spacing:.02em;line-height:1.25;white-space:nowrap}
.sn-links a span{
  font-size:10.5px;color:var(--dim);letter-spacing:.02em;line-height:1.3;
  max-width:150px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.sn-links a:hover{background:#ece7db}
.sn-links a.on{background:var(--ink);color:var(--paper)}
.sn-links a.on span{color:#c9c3b4}
@media(max-width:820px){
  .sn-brand{display:none}
  .sn-links{justify-content:space-between}
  .sn-links a{min-width:0;padding:10px 8px;flex:1;align-items:center}
  .sn-links a span{display:none}
}
/* 封面页收起顶栏，让封面更干净；改用封面自带的页脚导航进总览/来源 */
html.oncover .scalenav{display:none}
.coverfoot{
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;
  margin-top:30px;border-top:3px solid var(--ink);padding-top:16px;
}
.coverfoot .lbl{font-size:11px;letter-spacing:.26em;text-transform:uppercase;color:var(--dim);font-weight:800}
.coverfoot .lnks{display:flex;gap:30px;flex-wrap:wrap}
.coverfoot a{font-size:13.5px;font-weight:800;letter-spacing:.04em;display:flex;align-items:center;gap:7px}
.coverfoot a .ar{color:var(--red);transition:transform .18s}
.coverfoot a:hover .ar{transform:translateX(4px)}
.coverfoot a .sub2{font-weight:500;color:var(--dim);letter-spacing:.02em}

/* ---------- 报头 ---------- */
.masthead{
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;
  border-bottom:3px solid var(--ink);padding:22px 0 11px;
  font-size:12px;letter-spacing:.24em;text-transform:uppercase;
}
.masthead .brand{font-weight:800;letter-spacing:.1em}
.masthead .brand b{color:var(--red)}
.masthead .idx{color:var(--red);font-weight:700}

/* ---------- 封面：平台名 + 本次场景 ---------- */
h1{font-size:clamp(34px,5.6vw,78px);line-height:1;font-weight:900;letter-spacing:-.04em;margin:36px 0 0}
h1 .thin{font-weight:200}
h1 .box{background:var(--ink);color:var(--paper);padding:0 .1em;display:inline-block}
h1 .red{color:var(--red)}
.tagline{font-size:clamp(15px,1.5vw,18px);letter-spacing:.3em;color:var(--dim);margin-top:16px;font-weight:500}
.sub{
  display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:12px;
  border-top:1px solid var(--ink);border-bottom:1px solid var(--ink);
  padding:14px 0;margin-top:24px;
}
.sub .lead{font-size:16px;line-height:1.75;max-width:880px;color:#242424;text-wrap:pretty}
.sub .lead b{background:linear-gradient(transparent 62%,rgba(216,52,42,.26) 62%);font-weight:700}
.sub .hint{font-size:12px;letter-spacing:.2em;color:var(--dim);white-space:nowrap}

/* ---------- 三扇门（政府端 / 教师端 / 学生端） ---------- */
.doors{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid var(--ink);margin:30px 0 8px}
@media(max-width:880px){.doors{grid-template-columns:1fr}}
.door{
  position:relative;padding:42px 34px 30px;min-height:400px;
  display:flex;flex-direction:column;border-right:1px solid var(--ink);
  color:var(--ink);background:transparent;transition:background .2s,color .2s;
}
.door:last-child{border-right:0}
@media(max-width:880px){.door{border-right:0;border-bottom:1px solid var(--ink);min-height:0}.door:last-child{border-bottom:0}}
.door::before{content:"";position:absolute;left:0;right:0;top:0;height:6px;background:var(--band)}
.door .no{position:absolute;top:24px;right:32px;font-size:12px;font-weight:800;letter-spacing:.12em;color:var(--line)}
.door .tag{font-size:11px;letter-spacing:.28em;text-transform:uppercase;color:var(--tag);font-weight:800}
.door .role{font-size:clamp(46px,5.2vw,64px);font-weight:900;letter-spacing:-.035em;line-height:.98;margin-top:22px}
.door .rule{width:36px;height:3px;background:var(--band);margin-top:22px}
.door .scale{font-size:12.5px;letter-spacing:.24em;color:var(--dim);text-transform:uppercase;margin-top:14px}
.door .obj{font-size:14px;line-height:1.85;color:#2a2a2a;margin-top:auto;padding-top:30px}
.door .obj .lt{color:var(--tag);font-weight:800;margin-right:2px}
.door .metric{margin-top:14px}
.door .metric .v{font-size:52px;font-weight:900;letter-spacing:-.035em;line-height:1}
.door .metric .u{font-size:13px;color:var(--dim);margin-left:8px;letter-spacing:.02em}
.door .enter{
  margin-top:24px;padding-top:14px;border-top:1px solid var(--ink);
  display:flex;justify-content:space-between;align-items:center;
  font-size:13px;font-weight:800;letter-spacing:.1em;
}
.door .enter .ar{font-size:18px;transition:transform .18s}
.door:hover{background:var(--ink);color:var(--paper)}
.door:hover .no{color:#4a463b}
.door:hover .scale,.door:hover .metric .u{color:#bcb6a8}
.door:hover .obj{color:#d8d3c6}
.door:hover .rule{background:var(--clay)}
.door:hover .enter{border-top-color:rgba(255,255,255,.25)}
.door:hover .enter .ar{transform:translateX(6px)}
.door:hover .tag{color:var(--clay)}
.gov{--band:#141414;--tag:#141414}
.tea{--band:#c9a227;--tag:#8a6a12}
.stu{--band:#d8342a;--tag:#d8342a}

/* ---------- 尺度阶梯 ---------- */
.ladder{margin:40px 0 8px;display:flex;flex-direction:column;gap:10px}
.rung{display:grid;grid-template-columns:74px 1fr auto;align-items:center;gap:16px;padding:12px 14px;border:1px solid var(--line);background:#faf8f3;transition:.15s}
.rung:hover{border-color:var(--ink);background:#fff}
.rung .r-name{font-weight:900;font-size:16px;letter-spacing:.04em}
.rung .r-bar{height:24px;background:var(--ink);position:relative}
.rung:nth-child(2) .r-bar{background:#3a3a3a}
.rung:nth-child(3) .r-bar{background:var(--red)}
.rung .r-scope{font-size:13px;color:var(--dim);text-align:right;max-width:52%}
.rung .r-bar span{position:absolute;right:8px;top:0;bottom:0;display:flex;align-items:center;color:#f4f1ea;font-size:11px;letter-spacing:.1em}
@media(max-width:720px){.rung{grid-template-columns:64px 1fr}.rung .r-scope{display:none}}

/* ---------- 子页面（视图） ---------- */
.view{display:none;padding:44px 0 64px}
.view.on{display:block}
/* 视图内的次级分区（如总览页的三尺度对照） */
.vsub{border-top:3px solid var(--ink);margin-top:70px;padding-top:76px}
/* 区块标题 */
.sec-head{display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:20px;margin-bottom:12px}
.eyebrow{font-size:12px;letter-spacing:.26em;text-transform:uppercase;color:var(--red);font-weight:800}
.view h2{font-size:clamp(30px,5vw,62px);line-height:1;font-weight:900;letter-spacing:-.03em;margin-top:8px}
.view h2 .thin{font-weight:200;color:var(--dim)}
.boundary{
  max-width:420px;font-size:13.5px;color:#333;line-height:1.7;border-left:3px solid var(--clay);padding-left:14px;
}
.boundary b{color:var(--red)}
.sec-note{font-size:13px;color:var(--dim);margin:14px 0 30px;max-width:860px;line-height:1.75}

/* ---------- 双栏舞台 ---------- */
.stage{display:grid;grid-template-columns:1.05fr 1fr;gap:0;margin-top:34px;border:1px solid var(--ink)}
@media(max-width:840px){.stage{grid-template-columns:1fr}}
.block-black{background:var(--ink);color:var(--paper);padding:46px 42px}
.block-paper{padding:46px 42px}
.block-paper{border-left:1px solid var(--ink)}
@media(max-width:840px){.block-paper{border-left:0;border-top:1px solid var(--ink)}}
.blk-lbl{font-size:11px;letter-spacing:.26em;text-transform:uppercase;color:var(--clay);margin-bottom:24px;font-weight:700}
.mega{font-size:clamp(76px,12vw,140px);line-height:.82;font-weight:900;letter-spacing:-.05em}
.mega .of{font-size:26px;font-weight:300;color:var(--clay);letter-spacing:0}
.stamp{display:inline-block;margin-top:22px;background:var(--red);color:#fff;font-weight:800;font-size:15px;letter-spacing:.16em;padding:8px 16px;transform:rotate(-1.4deg)}
.bm{margin-top:24px;font-size:14px;color:#bdb8ac}
.bm b{color:var(--clay)}
.bm .ln{display:flex;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,.13);padding:7px 0}

/* ---------- 缺口/双向条 ---------- */
.gaps{display:flex;flex-direction:column;gap:20px}
.gap .top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px;gap:10px}
.gap .name{font-size:16px;font-weight:800}
.gap .gnote{font-weight:400;color:var(--dim);font-size:11.5px;margin-left:6px}
.gap .val{font-size:12.5px;color:var(--dim);font-variant-numeric:tabular-nums;white-space:nowrap}
.track{position:relative;height:22px;background:repeating-linear-gradient(90deg,#e7e3d9 0 1px,transparent 1px 22px);border-bottom:2px solid var(--ink)}
.fill{position:absolute;left:0;bottom:0;top:0;background:var(--ink)}
.fill.hot{background:var(--red)}
.zero{position:absolute;top:-4px;bottom:-2px;width:2px;background:var(--clay)}

.dual{display:grid;grid-template-columns:118px 1fr 92px;align-items:center;gap:12px;padding:5px 0}
.dual-name{font-size:13.5px;font-weight:700}
.dual-scale{display:flex;flex-direction:column;gap:3px}
.dbar{height:9px;background:#e7e3d9}
.dbar i{display:block;height:100%}
.dbar.sup i{background:var(--ink)}
.dbar.dem i{background:var(--red)}
.dual-val{font-size:12px;color:var(--dim);text-align:right;font-variant-numeric:tabular-nums;display:flex;justify-content:flex-end;gap:8px}
.dual-val b{color:var(--ink)}
.legend{display:flex;flex-wrap:wrap;gap:20px;font-size:12px;color:var(--dim);margin-top:22px}
.legend i{display:inline-block;width:16px;height:9px;margin-right:6px;vertical-align:middle}
.footnote{margin-top:16px;font-size:12px;color:#8f887a;line-height:1.65}

/* ---------- 数字卡 ---------- */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:1px solid var(--ink);margin-top:34px}
@media(max-width:820px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{padding:26px 24px;border-right:1px solid var(--line)}
.stat:last-child{border-right:0}
@media(max-width:820px){.stat:nth-child(2n){border-right:0}.stat:nth-child(-n+2){border-bottom:1px solid var(--line)}}
.stat-v{font-size:40px;font-weight:900;letter-spacing:-.03em;line-height:1}
.stat-v .stat-u{font-size:14px;font-weight:400;color:var(--dim);margin-left:5px;letter-spacing:0}
.stat-l{font-size:13.5px;font-weight:700;margin-top:10px}
.stat-n{font-size:11.5px;color:var(--dim);margin-top:5px;line-height:1.55}

/* ---------- TSI ---------- */
.tsi-grid{display:grid;grid-template-columns:340px 1fr;gap:44px;align-items:center;margin-top:36px}
@media(max-width:880px){.tsi-grid{grid-template-columns:1fr;gap:24px}}
.radar{width:100%;max-width:340px;height:auto;display:block;margin:0 auto}
.radar .rg{fill:none;stroke:#141414;stroke-opacity:.14}
.radar .ax{stroke:#141414;stroke-opacity:.2}
.radar .rpoly{fill:rgba(216,52,42,.14);stroke:var(--red);stroke-width:2.2;stroke-linejoin:round}
.radar .rdot{fill:var(--red)}
.radar .rlab{font-size:11.5px;fill:var(--dim);font-family:inherit}
.radar .rval{font-size:14px;font-weight:800;fill:var(--ink);font-family:inherit}
.tsi-head{display:flex;align-items:baseline;gap:14px;margin-bottom:6px}
.tsi-head .tv{font-size:52px;font-weight:900;letter-spacing:-.03em;line-height:1}
.tsi-head .tb{font-size:13px;color:var(--red);border:1px solid var(--red);padding:3px 12px;transform:rotate(-1deg)}
.tsi-meta{font-size:12.5px;color:var(--dim);margin-bottom:18px}
.tsi-meta b{color:var(--ink)}
.inds{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
@media(max-width:880px){.inds{grid-template-columns:repeat(2,1fr)}}
.ind{border:1px solid var(--line);padding:10px 11px;background:#faf8f3}
.ind.na{background:#efece3;border-style:dashed}
.ind-h{display:flex;justify-content:space-between;align-items:center;font-size:10.5px;color:var(--dim);letter-spacing:.06em}
.ind-id{font-weight:800;color:var(--red)}
.ind.na .ind-id{color:#a8a294}
.lv{display:inline-block;font-size:10px;font-weight:800;padding:1px 6px;border:1px solid currentColor;border-radius:2px}
.lv-a{color:#1c6b46}.lv-b{color:#2f6b8f}.lv-c{color:#a8761a}.lv-d{color:#b0531f}.lv-e{color:#8a8f9c}
.ind-n{font-size:12px;margin-top:6px;line-height:1.4;min-height:34px;font-weight:600}
.ind-v{font-size:19px;font-weight:900;margin-top:4px;font-variant-numeric:tabular-nums}
.ind.na .ind-v{color:#a8a294;font-size:14px;font-weight:700}

/* ---------- 通用表 ---------- */
.tbl{width:100%;border-collapse:collapse;margin-top:26px;font-size:13px}
.tbl th,.tbl td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line)}
.tbl thead th{border-bottom:2px solid var(--ink);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}
.tbl td.n,.tbl th.n{text-align:right;font-variant-numeric:tabular-nums}
.tbl tbody tr:hover{background:#faf8f3}

/* ---------- 时间线（在校生数） ---------- */
.tl{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:1px solid var(--ink);margin-top:30px}
@media(max-width:720px){.tl{grid-template-columns:repeat(2,1fr)}}
.tl .cell{padding:22px 20px;border-right:1px solid var(--line)}
.tl .cell:last-child{border-right:0}
@media(max-width:720px){.tl .cell:nth-child(2n){border-right:0}.tl .cell:nth-child(-n+2){border-bottom:1px solid var(--line)}}
.tl .yr{font-size:12px;letter-spacing:.12em;color:var(--dim)}
.tl .nv{font-size:44px;font-weight:900;letter-spacing:-.03em;line-height:1.05;margin-top:6px}
.tl .nv .up{color:var(--red)}
.tl .src{font-size:11px;color:#8f887a;margin-top:8px;line-height:1.5}

/* ---------- 简历池 ---------- */
.res-grid{display:grid;grid-template-columns:1fr 1fr;gap:34px 46px;margin-top:30px}
@media(max-width:820px){.res-grid{grid-template-columns:1fr}}
.res-h{font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--red);font-weight:800;margin-bottom:14px;border-bottom:2px solid var(--ink);padding-bottom:7px}
.hbar{display:grid;grid-template-columns:104px 1fr 62px;align-items:center;gap:10px;margin:7px 0;font-size:12.5px}
.hbar-l{color:#333;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hbar-t{height:13px;background:#e7e3d9}
.hbar-t i{display:block;height:100%;background:var(--ink)}
.hbar-v{text-align:right;color:var(--dim);font-variant-numeric:tabular-nums}

/* ---------- 微观 ---------- */
.persona{
  display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid var(--ink);margin-top:30px;
}
@media(max-width:760px){.persona{grid-template-columns:1fr}}
.persona .pcol{padding:26px 26px}
.persona .pcol + .pcol{border-left:1px solid var(--ink)}
@media(max-width:760px){.persona .pcol + .pcol{border-left:0;border-top:1px solid var(--ink)}}
.persona h4{font-size:13px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin-bottom:14px}
.persona .big{font-size:46px;font-weight:900;letter-spacing:-.03em;line-height:1}
.persona .big small{font-size:14px;font-weight:400;color:var(--dim);margin-left:6px}
.persona .psub{font-size:12.5px;color:var(--dim);margin-top:8px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}
.chip{font-size:11.5px;border:1px solid var(--line);padding:2px 9px;background:#faf8f3;border-radius:2px}
.chip.off{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip.na{opacity:.6;text-decoration:line-through}

.example-badge{display:inline-block;background:var(--red);color:#fff;font-size:11px;font-weight:800;letter-spacing:.2em;padding:4px 11px;transform:rotate(-1deg);vertical-align:middle;margin-left:12px}

.todo{display:grid;grid-template-columns:repeat(2,1fr);gap:0;border:1px solid var(--ink);margin-top:30px}
@media(max-width:760px){.todo{grid-template-columns:1fr}}
.todo .t{padding:24px 24px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
.todo .t:nth-child(2n){border-right:0}
.todo .t:nth-child(n+3){border-bottom:0}
@media(max-width:760px){.todo .t{border-right:0}.todo .t:last-child{border-bottom:0}}
.todo .t .th{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.todo .t .tn{font-size:17px;font-weight:900}
.todo .t .tgap{font-size:12px;color:var(--red);font-weight:700;white-space:nowrap}
.todo .t .ta{font-size:13.5px;margin-top:10px;line-height:1.65}
.todo .t .tg{font-size:11.5px;color:var(--dim);margin-top:9px;border-top:1px dashed var(--line);padding-top:8px}

/* ---------- 对照表 ---------- */
.cmp-tbl .cellbar{display:flex;align-items:center;gap:8px}
.cmp-tbl .cellbar i{height:10px;background:var(--ink);min-width:2px;display:block}
.cmp-tbl .cellbar.cdem i{background:var(--red)}
.cmp-tbl .cellbar span{font-size:12px;color:var(--dim);font-variant-numeric:tabular-nums;min-width:34px}
.cmp-tbl td.miss .cellbar i{background:#c9c3b4}

/* ---------- 来源 ---------- */
.src-grid{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid var(--ink);margin-top:30px}
@media(max-width:820px){.src-grid{grid-template-columns:1fr}}
.src-grid .s{padding:28px 28px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
.src-grid .s:nth-child(2n){border-right:0}
.src-grid .s h4{font-size:15px;font-weight:900;margin-bottom:6px}
.src-grid .s .sdesc{font-size:12.5px;color:var(--dim);margin-bottom:12px;line-height:1.6}
.skills-mini{display:grid;grid-template-columns:repeat(2,1fr);gap:4px 18px}
.skills-mini .sm{display:flex;justify-content:space-between;font-size:12.5px;border-bottom:1px dashed var(--line);padding:4px 0}
.skills-mini .sm b{font-variant-numeric:tabular-nums}
.src-block{margin-top:44px}
.src-block h3{font-size:20px;font-weight:900;margin-bottom:6px}
.src-block .sd{font-size:12.5px;color:var(--dim);margin-bottom:14px}
details.more{border:1px solid var(--line);margin-top:18px;background:#faf8f3}
details.more>summary{cursor:pointer;padding:13px 18px;font-size:13.5px;font-weight:700;list-style:none;display:flex;justify-content:space-between;align-items:center}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::after{content:"＋";color:var(--red);font-weight:900}
details.more[open]>summary::after{content:"－"}
details.more .dbody{padding:6px 18px 20px}
.missing-list{list-style:none;margin-top:10px}
.missing-list li{font-size:13px;padding:9px 0 9px 26px;border-bottom:1px dashed var(--line);position:relative;color:#333;line-height:1.65}
.missing-list li::before{content:"缺";position:absolute;left:0;top:9px;font-size:11px;font-weight:800;color:#fff;background:var(--red);padding:1px 6px;letter-spacing:.05em}
.cmd{font-family:"Consolas","Courier New",monospace;font-size:12px;background:var(--ink);color:#e9e4d6;padding:9px 14px;display:inline-block;margin:6px 8px 0 0;word-break:break-all}
.path{font-family:"Consolas","Courier New",monospace;font-size:12px;color:#3a3a3a;background:#efece3;padding:1px 6px}

/* ---------- 正文引用序号 + 参考来源清单 ---------- */
sup.ref{font-size:.7em;line-height:0;white-space:nowrap}
sup.ref a{color:var(--red);font-weight:800;text-decoration:none;padding:0 1px;transition:.15s}
sup.ref a:hover{background:var(--red);color:var(--paper)}
/* 黑底块内引用序号改浅红，保证对比度 */
.block-black sup.ref a{color:#e9a79f}
.block-black sup.ref a:hover{background:#e9a79f;color:#141414}
.refs{list-style:none;margin:8px 0 0;padding:0;counter-reset:none}
.refs>li{display:flex;gap:16px;padding:16px 0;border-top:1px solid var(--line)}
.refs>li:first-child{border-top:0}
.refs .rn{flex:0 0 auto;font-weight:800;color:var(--red);font-size:15px;letter-spacing:.02em;min-width:34px}
.refs .rbody{flex:1 1 auto;min-width:0}
.refs .rt{font-weight:800;font-size:15.5px;letter-spacing:-.01em;margin-bottom:6px}
.refs .rw{font-size:13px;line-height:1.72;color:#2a2a2a;margin-top:3px;text-wrap:pretty}
.refs .rw b{display:inline-block;min-width:34px;color:var(--dim);font-size:11px;letter-spacing:.14em;font-weight:800;margin-right:8px;vertical-align:1px}
.refs .ru{font-size:12px;color:var(--dim);margin-top:8px}
.refs .ru a{color:var(--red);font-weight:700;text-decoration:none;margin-right:10px}
.refs .ru a:hover{text-decoration:underline}
/* 跳转落点避开粘性导航 */
[id^="ref-"]{scroll-margin-top:86px}
a[id^="c"]{scroll-margin-top:86px}

/* ---------- 页脚 ---------- */
.folio{margin-top:64px;border-top:3px solid var(--ink);padding:20px 0 80px;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px}

.totop{position:fixed;right:22px;bottom:22px;z-index:40;background:var(--ink);color:var(--paper);width:46px;height:46px;display:flex;align-items:center;justify-content:center;font-size:18px;border-radius:50%;box-shadow:0 8px 26px rgba(0,0,0,.25);opacity:0;pointer-events:none;transition:.25s}
.totop.on{opacity:1;pointer-events:auto}
@media print{.scalenav,.totop{display:none}.view{display:block!important}}

/* ---------- TSI Tree（可展开：维度 → 指标 → 技能 → 证据） ---------- */
.door .door-sub{font-size:12px;line-height:1.6;color:var(--dim);margin-top:8px;padding-top:8px;border-top:1px dashed #d9d4c6}
.tsi-tree{border:1px solid var(--rule);background:#fbfaf6;margin:22px 0 0}
.tsi-tree>summary{cursor:pointer;padding:14px 18px;font-size:15px;list-style:none;display:flex;justify-content:space-between;align-items:center;gap:12px}
.tsi-tree>summary::-webkit-details-marker{display:none}
.tsi-tree>summary::after{content:"▾";color:var(--red);font-weight:700}
.tsi-tree[open]>summary::after{content:"▴"}
.tsi-tree .tleaf{padding:0 18px 14px 18px;font-size:13px;line-height:1.95;color:#3a3a3a}
.tsi-tree .root-note{color:var(--dim);border-bottom:1px solid #e8e4d8;padding-bottom:12px}
.tnode{border-left:2px solid #ded9cb;margin:6px 0 6px 2px;padding-left:10px}
.tnode>summary{cursor:pointer;list-style:none;display:flex;align-items:baseline;gap:10px;padding:4px 0}
.tnode>summary::-webkit-details-marker{display:none}
.tnode.dim>summary{border-bottom:1px dashed #e2ded2}
.tnode .tid{display:inline-block;min-width:26px;color:var(--clay);font-weight:700}
.tnode .tv-mini{margin-left:auto;color:var(--dim);font-variant-numeric:tabular-nums}
.tnode .tleaf{border-left:1px dashed #e8e4d8;padding-left:12px;margin-left:8px}
"""

JS = r"""
(function(){
  // 子页面路由：#overview / #macro / #meso / #micro / #source
  var views = Array.prototype.slice.call(document.querySelectorAll('.view'));
  var links = Array.prototype.slice.call(document.querySelectorAll('.sn-links a'));
  var HOME = 'cover';
  function route(){
    var h = (location.hash || '').replace('#','') || HOME;
    var el = document.getElementById(h);
    // 若 hash 指向子页内的锚点（引用序号 #cN / 来源条目 #ref-N），定位到它所属的子页
    var v = el;
    if(v && views.indexOf(v) < 0){ v = v.closest ? v.closest('.view') : null; }
    if(!v){ v = document.getElementById(HOME); h = HOME; el = v; }
    views.forEach(function(x){ x.classList.toggle('on', x === v); });
    links.forEach(function(a){ a.classList.toggle('on', a.getAttribute('href') === '#' + h); });
    // 封面页收起顶栏（封面自带 masthead 与页脚导航），子页恢复
    document.documentElement.classList.toggle('oncover', !!v && v.id === HOME);
    if(el && views.indexOf(el) < 0){
      // 滚到该锚点。用瞬时定位，避免与 html 的 scroll-behavior:smooth 打架；
      // 双 rAF 等子页 display 切换后的布局稳定，落点才准（避开粘性导航由 scroll-margin-top 保证）。
      var go = function(){
        try{ el.scrollIntoView({block:'start', behavior:'instant'}); }
        catch(e){ el.scrollIntoView(true); }
      };
      requestAnimationFrame(function(){ requestAnimationFrame(go); });
    } else {
      window.scrollTo({top:0, left:0, behavior:'instant'});
    }
  }
  window.addEventListener('hashchange', route);
  route();
  // 回到顶部按钮
  var top = document.querySelector('.totop');
  if(top){
    window.addEventListener('scroll', function(){
      top.classList.toggle('on', window.scrollY > 600);
    }, {passive:true});
  }
})();
"""
