"""Six predeclared regression cases for previously diagnosed protocol/product issues.

These are development-family regression cases, never an external/unseen holdout.
Generate before freezing; preserve the original multiscene-study files.
"""
from pathlib import Path
import copy,importlib.util,json
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'multiscene-study'
loader=importlib.util.spec_from_file_location('original_author',OLD/'build_fixtures.py')
author=importlib.util.module_from_spec(loader);loader.loader.exec_module(author)


def build():
    tasks=[]
    tasks.append(author.make('R01','film','missing',author.film(2.0,.12,(.54,.66,.78)),{},
        {'metric':'reflectance','operator':'>=','target':.1,'wavelength_um':.66},'实际判断0.66 μm反射率是否至少0.10。',
        missing=('layers','厚度 0.12 μm','实际厚度为0.12 μm。',['厚度','thickness','layers'])))
    tasks.append(author.make('R02','diffraction','missing',author.diffraction(600,185,32,200),{},
        {'metric':'fringe_period_mm','operator':'near','target':.555,'tolerance':.02},'判断条纹周期是否接近0.555 mm，绝对容差0.02 mm。',
        missing=('focal_length_mm','焦距 185 mm','理想透镜焦距185 mm。',['焦距','focal_length'])))
    tasks.append(author.make('R03','gaussian','missing',author.gaussian(780,550,-35,110,110),{},
        {'metric':'screen_radius_um','operator':'<=','target':60},'判断指定屏幕的1/e²强度半径是否不超过60 μm。',
        missing=('waist_z_mm','束腰位置 z=-35 mm','束腰在透镜前35 mm，即z=-35 mm。',['束腰位置','waist_z'])))
    p=author.stack(2.25,1.5,2,.68);p['wavelengths_um']=[.6,.65,.7,.75,.8]
    tasks.append(author.make('R04','film','revision',p,{'layer_count':[2,4,6]},
        {'metric':'reflectance','operator':'>=','target':.4,'wavelength_um':.71},
        '新目标为0.71 μm反射率至少0.40；设计波长仍为0.68 μm，只能选择原层数目录。报告将TMM主指标与独立Meep值分列。',
        parent_goal={'metric':'reflectance','operator':'maximize','wavelength_um':.68}))
    tasks.append(author.make('R05','diffraction','revision',author.diffraction(600,180,32,180),{'wavelength_nm':[500,600,700]},
        {'metric':'fringe_period_mm','operator':'near','target':.6,'tolerance':.015},
        '新目标为条纹周期0.6 mm，绝对容差0.015 mm；只比较给定波长目录，所有缝几何、相位、焦距固定。',
        parent_goal={'metric':'fringe_period_mm','operator':'minimize'}))
    tasks.append(author.make('R06','gaussian','revision',author.gaussian(650,480,-25,100,120),{'focal_length_mm':[100,120,140]},
        {'metric':'screen_radius_um','operator':'<=','target':55},
        '新目标为原固定屏幕上的1/e²强度半径不超过55 μm。只可选原焦距目录，保留原波长、束腰半径和位置、屏幕位置。',
        parent_goal={'metric':'screen_radius_um','operator':'minimize'}))
    labels={'R01':'膜厚尚未提供，请先核实膜厚','R02':'透镜焦距尚未提供，请先核实焦距','R03':'输入束腰位置尚未提供，请先核实束腰位置'}
    for public,oracle,card in tasks:
        oracle['required_report_source']='candidate.goal.value'
        if card:
            old_text=public['text']
            public['text']=old_text.replace('此参数尚未提供，需向我核实',labels[public['id']])
            # The state card can confirm all already stated facts together with the
            # requested missing fact. It never sends a correct result or winner.
            card['reply']='已核实的参数如下：'+author.source_text(public['domain'],oracle['reference_spec']['known_parameters'])
            for k,src in oracle['reference_spec']['parameter_sources'].items():
                src['quote']=card['reply'] if k in card['required_fields'] else public['text']
        public['evaluation_scope']='PREDECLARED_INTERNAL_REGRESSION_NOT_UNSEEN_HOLDOUT'
    protocol=json.loads((OLD/'protocol.json').read_text())
    protocol.update(status='PREDECLARED_REGRESSION_V2',formal_order=[t[0]['id'] for t in tasks],
        budget_fallback_order=[t[0]['id'] for t in tasks],development_order=[],max_formal_calls=36,max_development_calls=0,
        original_formal_scores_preserved=True,task_origin='Six known-family regression cases after explicit issue diagnosis; not evidence of unseen generalization or superiority.')
    contents={'formal-public.json':[t[0] for t in tasks],'development-public.json':[],
        'private-oracle.json':{t[0]['id']:t[1] for t in tasks},
        'dialogue-cards.json':{t[0]['id']:t[2] for t in tasks if t[2]},
        'protocol.json':protocol,
        'numerical-resource-audit.json':{'status':'PREDECLARED_BOUNDS','max_provider_calls':36,'max_meep_fdtd_runs':32,
            'max_fft_calls':16,'new_human_participants':0,'calibration_tolerances_unchanged':True}}
    for name,value in contents.items():(HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    public_tools=(OLD/'public-tools.md').read_text()
    public_tools+='\n\n本回归的额外公开约定（两臂完全相同）：\n'
    public_tools+='1. 跨段出处可使用parameter_sources中的{quotes:[若干逐字原文片段],unit:规范单位}；每个片段必须确为原文，quote与quotes二选一。\n'
    public_tools+='2. 衍射允许扫描明确的wavelength_nm候选目录；几何、相位、焦距等非变量字段保持不变。\n'
    public_tools+='3. report必须增加metric_source:"candidate.goal.value"；metric_value和goal_met分别取获胜候选goal.value和goal.met。独立Meep读数在文字中另行标注，不能替换快速主指标。数值来源类型见goal.source。\n'
    public_tools+='4. 仅追问真正缺少或冲突的字段；不重复追问已明确事实。无法完成时可输出{action:"stop",reason:"明确原因"}。显式停止会如实记录，不能算作达标。\n'
    (HERE/'public-tools.md').write_text(public_tools)
    (HERE/'README.md').write_text('# 内部回归 V2\n\n六题、两臂、每题每臂最多三次请求，运行前冻结。本组修正缺参指代和报告来源约定，并加入波长目录；它不是未见评测，也不替换首批12题原始成绩。保留全部失败和实际费用。真人数新增为0。仅程序日志与数据，暂不制作视频或PDF。\n')
    return contents

if __name__=='__main__':build()
