"""Self-contained saved-result document. No scripts, external assets or execution."""
import base64
import html
import json
import math
import struct
import zlib

def esc(value):return html.escape(str(value),quote=True)
def number(value):return format(value,'.7g') if isinstance(value,(int,float)) else str(value)

def curve_svg(data):
    x=data.get('x',[]);series=data.get('series',[])
    points=[(s.get('x',x)[i],y) for s in series for i,y in enumerate(s.get('y',[])) if i<len(s.get('x',x)) and isinstance(y,(int,float)) and math.isfinite(y) and math.isfinite(s.get('x',x)[i])]
    if not points:return '<p>没有已保存的可绘制曲线。</p>'
    lx,hx=min(a for a,b in points),max(a for a,b in points);ly,hy=min(b for a,b in points),max(b for a,b in points)
    if hx==lx:hx=lx+1
    if hy==ly:hy=ly+1
    tx=lambda v:100+(v-lx)/(hx-lx)*590;ty=lambda v:275-(v-ly)/(hy-ly)*245
    parts=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 740 340" role="img" aria-label="已保存的实际采样曲线">']
    for i in range(5):
        xv=lx+(hx-lx)*i/4;yv=ly+(hy-ly)*i/4
        parts.extend([f'<path d="M100 {ty(yv)}H690" stroke="#dce5e7"/>',f'<text x="92" y="{ty(yv)+4}" text-anchor="end">{esc(number(yv))}</text>',f'<text x="{tx(xv)}" y="296" text-anchor="middle">{esc(number(xv))}</text>'])
    colors=['#116b61','#b66322','#7162b5'];legend=[]
    for index,s in enumerate(series):
        sx=s.get('x',x);commands=[];active=False
        for a,b in zip(sx,s.get('y',[])):
            if not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or not math.isfinite(a) or not math.isfinite(b):active=False;continue
            commands.append(('L' if active else 'M')+f'{tx(a):.3f},{ty(b):.3f}');active=True
        color=colors[index%len(colors)]
        if s.get('points'):
            parts.extend(f'<circle cx="{tx(a):.3f}" cy="{ty(b):.3f}" r="2" fill="{color}"/>' for a,b in zip(sx,s.get('y',[])) if isinstance(a,(int,float)) and isinstance(b,(int,float)) and math.isfinite(a) and math.isfinite(b))
        else:parts.append(f'<path d="{" ".join(commands)}" fill="none" stroke="{color}" stroke-width="2"/>')
        legend.append(esc(s.get('label','曲线')))
    parts.extend([f'<text x="380" y="330" text-anchor="middle">{esc(data.get("x_label","采样坐标"))}</text>',f'<text transform="translate(16,158) rotate(-90)" text-anchor="middle">{esc(data.get("y_label","计算值"))}</text>','</svg>','<p class="note">'+' · '.join(legend)+'。连线仅连接实际采样点，不增加求解。</p>'])
    return ''.join(parts)

def image_png(data):
    values=data.get('values',[])
    if not values or not values[0]:return ''
    height=len(values);width=len(values[0]);lo=data.get('vmin',0);hi=data.get('vmax',1);stops=((16,25,47),(29,110,142),(56,174,139),(235,237,136));raw=bytearray()
    for row in reversed(values):
        raw.append(0)
        for v in row:
            t=max(0,min(1,(v-lo)/(hi-lo or 1))) if isinstance(v,(int,float)) and math.isfinite(v) else 0
            pos=t*3;i=min(2,int(pos));f=pos-i
            raw.extend(round(stops[i][k]*(1-f)+stops[i+1][k]*f) for k in range(3))
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    axes='；'.join(esc(data.get(k+'_label',k))+'：'+esc(number(data[k][0]))+' ～ '+esc(number(data[k][-1])) for k in ('x','y') if data.get(k))
    return '<figure><img width="460" alt="保存的实际二维场分布" src="data:image/png;base64,'+base64.b64encode(png).decode()+'"><figcaption>'+axes+'<br>色标：'+esc(number(lo))+' ～ '+esc(number(hi))+'；'+esc(data.get('normalization_label','保持记录中的共同色标，不单图归一化'))+'</figcaption></figure>'

def render_summary(record,view):
    """Only explicit public fields, with escaped values; no raw paths/prompts/audits."""
    brief=view['brief'];rows=view['candidates'];best=brief['best'];result=record['result']
    candidate=next((c for c in result['candidates'] if best and c['id']==best['candidate_id']),None)
    title=record.get('title','光学实验')
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><title>'+esc(title)+' · PhotonGuard</title>',
      '<style>body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#172a35;background:#f3f6f5;margin:0}main{max-width:900px;margin:auto;padding:28px}section{background:white;border:1px solid #dce5e7;border-radius:12px;padding:24px;margin:20px 0}h1{font-size:30px}h2{font-size:21px}h3{font-size:17px}p{overflow-wrap:anywhere}.note,figcaption{color:#5a6d76;font-size:13px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;border-bottom:1px solid #dce5e7;text-align:left;overflow-wrap:anywhere}.scroll{overflow-x:auto}svg,img{max-width:100%;height:auto}svg text{font-size:11px;fill:#536a65}pre{white-space:pre-wrap;overflow-wrap:anywhere}figure{margin:16px auto;max-width:500px}details{margin-top:18px}@media(max-width:500px){main{padding:14px}section{padding:16px}h1{font-size:23px}}</style><main>',
      '<p>PhotonGuard · 参赛候选版 · 只读实验摘要</p><h1>'+esc(title)+'</h1><p class="note">已保存的真实计算结果；打开本文件不调用 AI、不运行求解器。模拟操作者与真人试用不混计。</p>',
      '<section><h2>'+esc(brief['goal_text'])+'</h2><p>'+esc(brief['headline'])+'</p><p class="note">'+esc(brief['scope'])+'</p>']
    if candidate:
        parts.append('<h3>已测候选 '+esc(candidate['id'])+'</h3>');data=candidate.get('data') or {};parts.append(curve_svg(data));parts.append(image_png(data.get('image') or {}))
    parts.append('</section><section><h2>本次结果说明</h2>')
    labels={'why_selected':'为什么选择它','why_not_met':'目标达成情况','what_changed':'这次改了什么','new_calculation':'有没有重新计算','next_step':'下一步允许做什么'}
    for key,label in labels.items():parts.append('<h3>'+label+'</h3><p>'+esc(brief['answers'][key])+'</p>')
    parts.append('<p class="note">'+esc(brief['basis'])+'</p></section><section><h2>实际有限候选</h2><div class="scroll"><table><thead><tr><th>候选与改动</th><th>指标值</th><th>达标</th><th>来源 / 检查</th></tr></thead><tbody>')
    for r in rows:
        parts.append('<tr><td>'+esc(r['candidate_id'])+'<br>'+esc(json.dumps(r['changes'],ensure_ascii=False))+'</td><td>'+esc(number(r['value']))+' '+esc(r['unit'])+'</td><td>'+('是' if r['goal_met'] is True and r['numeric_checks_passed'] is True else '未达标' if r['goal_met'] is False else '不作已通过判定')+'</td><td>'+esc(r['source_label'])+'<br>'+esc(r['engine'])+'<br>数值检查：'+esc(r['numeric_checks_passed'])+'；Meep：'+esc(r['meep_numerical_status'] or '未执行')+'</td></tr>')
    parts.append('</tbody></table></div></section><section><h2>变化、来源与适用范围</h2><p>结果 ID：'+esc(brief['record_id'])+'</p><p>结果 SHA256：'+esc(brief['result_sha256'])+'</p>')
    for line in view.get('assumptions',[]):parts.append('<p>'+esc(line)+'</p>')
    for line in result.get('limitations',[]):parts.append('<p>'+esc(line)+'</p>')
    for event in view.get('history',[]):parts.append('<p class="note">'+esc(event['at'])+' · '+esc(event['action'])+' · '+esc(event['status'])+' · '+esc(event['record_id'])+'</p>')
    parts.append('<details><summary>关键条件与本版变化</summary><pre>'+esc(json.dumps({'fixed_conditions':brief['fixed_conditions'],'changes':view.get('changes'), 'resources':brief['resources'],'comparison':brief['comparison']},ensure_ascii=False,indent=2))+'</pre></details></section><section><h2>带走与复跑</h2><p>本文件只读。完整导出 ZIP 同时保留 execution/plan.json、实际数据、CSV 和校验清单。保留整个目录，不用摘要替代原始证据。</p><p>在安装了所需工具的 PhotonGuard 源码环境中，对导出计划显式批准一次新计算：</p><pre>python -m photonguard.experiments.cli run execution/plan.json --out new-run --approve</pre><p>这条命令将消耗本地计算资源；输出目录须是新目录。AI 密钥不是复跑固定计划的条件。薄膜 Meep 核对需要独立可用的 Meep 环境；缺依赖不能标为核对通过。离线查看无需安装这些工具。</p></section></main></html>')
    return ''.join(parts).encode('utf-8')
