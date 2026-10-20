"""One observation-result projection shared by UI, model context and export."""
import csv
import io
import json
from ..core import digest
from .observations import preview
from .summary_html import curve_svg, esc


def explanation(record,focus='overview'):
    """All numbers and cautions come from this version, never model prose."""
    from .observation_dialogue import LABELS
    r=record.get('fit_result');settings=record.get('fit_settings') or {}
    if not r:
        from .inference import issues
        questions=record.get('questions',[]) or issues(record['observation'],settings)[0]
        text='；'.join(questions) if questions else '当前条件和数值配置已形成草稿；核对来源与范围后再明确批准拟合。'
        for path,label in LABELS.items():text=text.replace(path.split('.')[-1],label)
        return text+' 数值配置建议不是实验测量，也没有启动计算。'
    p=r.get('estimated_parameters',{});res=r['resources'];parts=[]
    if focus in ('overview','parameters') and p:
        f=settings['fixed'];parts.append(f"在波长 {f['wavelength_nm']:g} nm、焦距 {f['focal_length_mm']:g} mm、缝宽 {f['slit_width_um']:g} μm、相位 0 的已知条件下，缝距模型估计为 {p['slit_separation_um']:.6g} μm。中心偏移 {p['center_shift_mm']:.6g} mm、幅度 {p['amplitude']:.6g}、背景 {p['background']:.6g} 是观测干扰参数，不是新的器件尺寸。")
    if focus in ('overview','residuals','outliers') and r.get('metrics'):
        a,b=r['metrics']['training'],r['metrics']['holdout']
        parts.append(f"同一原始扫描保留 {record['observation']['rows']} 点；训练 {a['count']} 点、预先留出 {b['count']} 点，RMSE 分别为 {a['rmse']:.6g}、{b['rmse']:.6g}（相对强度）。原始点、预测和残差都来自记录 {record['id'][:8]}，留出点不是独立实验。")
    if focus in ('outliers','residuals'):
        parts.append('本次 soft_l1 鲁棒损失降低较大残差的影响，所有原始点仍保留。没有普通最小二乘对照运行，不能给出改善百分比。' if settings.get('loss')=='soft_l1' else '本次采用 linear 普通平方残差，所有点均保留，没有启用鲁棒降权。')
        parts.append('残差可能来自噪声、异常观测或模型不适用；仅凭残差不能确定仪器故障。')
    labels={'BOUNDARY_HIT':'估计碰到允许范围边界，请核对范围出处；不能自动扩大',
      'INSUFFICIENT_INFORMATION':'扫描覆盖、采样或参数可辨识性不足；需要更有信息量的观测，不能据收敛断言唯一',
      'MULTIPLE_COMPARABLE_SOLUTIONS':'多个起点得到相近质量但不同的解，当前不能唯一采用',
      'POSSIBLE_MODEL_MISMATCH':'留出残差或相关性提示可能失配，需核对光路与观测模型',
      'RESOURCE_STOP':'达到资源限制，未完成原定起点搜索，没有自动重试'}
    if r.get('warnings'):parts.append('当前限制：'+'；'.join(labels.get(k,k) for k in r['warnings'])+'。')
    elif not r.get('usable_for_forward'):parts.append('当前没有可采用的收敛估计；保留起点和失败记录。')
    failed=sum(not x.get('success') for x in r['starts'])
    parts.append(f"已尝试 {res['starts_attempted']}/{res['starts_planned']} 个起点，{failed} 个未收敛或停止，实际残差调用 {res['actual_residual_calls']} 次。起点只改变缝距，其他三项从范围中点开始，不是四参数全空间搜索。")
    if focus in ('overview','next_step','limitations'):
        parts.append('可明确采用模型估计，补充并确认缝高和网格后另建正向核对。FFT 是同模型自洽检查，不是独立测量；新的周期目标需另外提出。' if r.get('usable_for_forward') else '当前暂停唯一参数的正向采用；应先处理以上具体诊断，已有条件无需全部重填。')
    parts.append('MODEL_ESTIMATE / ESTIMATE_READY 均不代表实测真值、严格唯一性或可信百分比。')
    return '\n\n'.join(parts)


def view(record):
    r=record.get('fit_result')
    return {'record_id':record['id'],'revision':record['revision'],'status':record['status'],
            'kind':'observation','dataset':preview(record['observation']),
            'settings':record.get('fit_settings'),'plan_sha256':(record.get('fit_plan') or {}).get('sha256'),
            'result_sha256':digest(r) if r else None,'questions':record.get('questions',[]),
            'fit_status':r.get('status') if r else None,'estimated_parameters':r.get('estimated_parameters') if r else None,
            'metrics':r.get('metrics') if r else None,'diagnostics':r.get('diagnostics') if r else None,
            'warnings':r.get('warnings',[]) if r else [],'resources':r.get('resources') if r else None,
            'usable_for_forward':bool(r and r.get('usable_for_forward')),
            'source_kind':'MODEL_ESTIMATE' if r else None,
            'scope':'模型估计，不是实测缝距；不提供置信百分比或唯一性证明。',
            'forward_children':record.get('forward_children',[]),'ai_guidance':record.get('fit_ai_guidance'),
            'field_sources':record.get('observation_facts',{}),'numerical_recipe':record.get('numerical_recipe'),
            'explanation':explanation(record)}


def table(record):
    r=record.get('fit_result') or {};data=r.get('data')
    if not data:raise ValueError('没有可导出的拟合预测')
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['position_mm','observed_relative','predicted_relative','residual','holdout'])
    writer.writerows(zip(data['x'],data['observed'],data['predicted'],data['residual'],map(int,data['holdout'])))
    return out.getvalue().encode('utf-8-sig')


def summary(record):
    value=view(record);r=record.get('fit_result') or {}
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
       '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>数据与模型估计 · PhotonGuard</title>',
       '<style>body{max-width:960px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;color:#183e36}svg{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ddd}</style>',
       '<h1>'+esc(record['title'])+'</h1><p>'+('已保存的实际拟合。' if r else '已保存的数据任务，尚无拟合结果。')+'打开不运行计算或 AI。'+esc(value['scope'])+'</p>',
       '<p>数据来源：'+esc(value['dataset']['source_kind'])+' · '+esc(value['dataset']['source_name'])+'</p>',
       '<p>数据指纹：'+esc(value['dataset']['sha256'])+'</p><h2>状态与诊断</h2><pre>'+esc(json.dumps(value,ensure_ascii=False,indent=2))+'</pre>']
    if r.get('data'):
        parts+=['<h2>原始点与原坐标模型预测</h2>'+curve_svg(r['data']),
                '<h2>残差</h2>'+curve_svg({'x':r['data']['x'],'x_label':'位置（mm）','y_label':'观测 − 预测','series':[{'label':'原始残差','y':r['data']['residual']}]}),
                '<h2>全部起点（包括未收敛和失败）</h2><pre>'+esc(json.dumps(r['starts'],ensure_ascii=False,indent=2))+'</pre>']
    return (''.join(parts)+'</html>').encode('utf-8')
