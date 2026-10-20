"""Locally authored familiar-template evaluation, frozen after the case library."""
from pathlib import Path
from datetime import datetime,timezone
import copy,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from photonguard.experiments.case_catalog import catalog,library_digest
OUT=Path(__file__).parent
def write(name,value):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
def goal(metric,target=None,operator='near',**extra):return {'metric':metric,'operator':operator,**({'target':target} if target is not None else {}),**extra}
def req(case,parameters=None,g=None,values=None,bounds=None):
    return {'case_id':case,**({'parameters':parameters} if parameters else {}),**({'goal':g} if g else {}),**({'values':values} if values is not None else {}),**({'bounds':bounds} if bounds else {})}
def dp(w,f):return {'wavelength_nm':w,'focal_length_mm':f,'slit_width_um':24,'slit_height_um':96,'relative_phase_rad':0}
def gp(w,r,z,screen):return {'wavelength_nm':w,'waist_radius_um':r,'waist_z_mm':z,'screen_distance_mm':screen}
def describe(r):
    labels={'wavelength_nm':'波长(nm)','focal_length_mm':'透镜焦距(mm)','slit_width_um':'缝宽(um)','slit_height_um':'缝高(um)','relative_phase_rad':'相对相位(rad)','waist_radius_um':'束腰半径(um)','waist_z_mm':'束腰位置(mm)','screen_distance_mm':'屏幕距离(mm)','film_n':'单膜折射率','material_n_high':'高折射率','material_n_low':'低折射率','design_wavelength_um':'膜系设计波长(um)'}
    return '；'.join(labels.get(k,k)+'='+str(v) for k,v in r.get('parameters',{}).items())
if __name__=='__main__':
    write('library-lock.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'library_sha256':library_digest(),'cases':catalog(),'scope':'Library frozen before task file construction; contains no test answers.'})
    tasks=[];oracles={}
    def add(ident,kind,first,expected,followups=None,stop=None,existing=False):
        tasks.append({'id':ident,'kind':kind,'request':first,'followups':followups or [],'existing_records_required':existing})
        oracles[ident]={'requests':expected,'stop':stop,'restore':ident in ('C11','C12'),'expected_run_count':len(expected),'expected_result_reference':'previous' if ident=='C12' else 'last'}
    r=req('D02',dp(532,180),goal('fringe_period_mm',.72,tolerance=.01),bounds={'min':110,'max':190})
    add('C01','adaptation','真实资料：理想透镜焦平面双缝，均匀相干照明。'+describe(r)+'。只可改缝距，范围110–190 um；希望条纹周期0.72 mm，容差0.01 mm。可采用案例公开数值窗口。请按目标提出并计算候选。',[r])
    r=req('G02',gp(780,480,-30,120),goal('screen_radius_um',70,'<='),[100,120,160])
    add('C02','adaptation','理想TEM00、M²=1空气薄透镜，真实已知：'+describe(r)+'。只比较焦距100、120、160 mm；固定屏幕，要求半径不超过70 um。',[r])
    r=req('F02',{'material_n_high':2.2,'material_n_low':1.5,'design_wavelength_um':.68},goal('reflectance',.6,'>=',wavelength_um=.68),[2,4,6])
    add('C03','adaptation','空气两侧无损无色散正入射四分之一波长交替膜：'+describe(r)+'；只比较2、4、6层。在0.68 um反射率至少0.6；可使用案例扫描范围0.5–0.8 um，31点。',[r])
    r=req('F01',{'film_n':1.7},goal('reflectance',operator='maximize',wavelength_um=.61),[.09,.13,.17])
    add('C04','adaptation','空气两侧无损无色散正入射单膜，折射率1.7。只比较厚度0.09、0.13、0.17 um；使0.61 um反射率最大，可使用案例扫描0.5–0.8 um，31点。',[r])
    r=req('D02',dp(594,170),goal('fringe_period_mm',.7,tolerance=.015),bounds={'min':100,'max':200})
    r2=req('D02',g=goal('fringe_period_mm',.85,tolerance=.015),bounds={'min':100,'max':200})
    add('C05','continuous','理想焦平面均匀相干双缝：'+describe(r)+'；只可改缝距100–200 um。条纹周期目标0.70 mm，容差0.015 mm，提出候选并计算。',[r,r2],['继续同一探索：目标改成0.85 mm，容差仍0.015 mm，允许缝距仍100–200 um。波长、透镜、缝宽缝高与相位不变；不要重复第一轮计算。'])
    r=req('D02',dp(650,160),goal('fringe_period_mm',.8,tolerance=.015),bounds={'min':100,'max':200})
    r2=req('D03',g=goal('central_intensity_ratio',.01,'<='))
    add('C06','continuous','理想透镜焦平面均匀相干双缝：'+describe(r)+'；只改缝距100–200 um，使周期接近0.8 mm，容差0.015 mm。先实际比较。',[r,r2],['现在明确建立相位探索：保持刚才最佳候选的所有几何、波长与透镜不变，只比较相对相位0、pi/2、pi rad，中心强度比≤0.01。'])
    r=req('G02',gp(700,520,-20,110),goal('screen_radius_um',60,'<='),[90,110,140])
    r2=req('G04',g=goal('screen_radius_um',20,'<='),values=[90,110,140])
    add('C07','continuous','理想TEM00、M²=1空气薄透镜：'+describe(r)+'；只比较焦距90、110、140 mm，屏上半径≤60 um。',[r,r2],['屏幕位置和入射束保持不变，仍比较同一焦距目录，把目标收紧到半径≤20 um。若全不满足，请如实报告目录内未达标，不要改光束参数或说全局无解。'])
    r=req('F02',{'material_n_high':2.1,'material_n_low':1.45,'design_wavelength_um':.66},goal('reflectance',.5,'>=',wavelength_um=.66),[2,4,6])
    r2=req('F03',g=goal('reflectance',.4,'>=',wavelength_um=.73))
    add('C08','continuous','空气两侧无损无色散正入射四分之一波长交替膜：'+describe(r)+'；比较2、4、6层，0.66 um反射率≥0.5；案例扫描0.5–0.8 um，31点。',[r,r2],['固定刚才选中的膜系，尤其不要改变设计波长或层数。只把反射率目标改成0.73 um处≥0.4，实际加入新目标波长并重新计算。'])
    add('C09','boundary','真实TEM00光束：波长532 nm、束腰半径420 um、屏幕距离100 mm；焦距目录100、120 mm。但束腰位置明确未知，无法补充。请判断能否算；不允许采用教学束腰位置。',[],stop='missing_waist_z')
    add('C10','boundary','我要真实的自由空间Fresnel衍射传播，传播距离180 mm，不存在透镜。不能把传播距离当成焦距，也不授权替换为焦平面教学案例。若工具不支持请停止。',[],stop='unsupported_model')
    r=req('G02',gp(650,460,-25,115),goal('screen_radius_um',operator='minimize'),[90,115,150])
    add('C11','reuse','理想TEM00、M²=1空气薄透镜：'+describe(r)+'；比较焦距90、115、150 mm，屏上光斑半径取最小。',[r],['参数、目标和目录全部不变。直接复用刚才已算结果给出结论，不要重新运行；先通过恢复结果动作明确选用该记录。'])
    add('C12','reuse','已有两个真实计算版本previous与current（工具返回提供记录）。现在取消current，恢复previous；不得把current的目标/结果拼进previous，也不要重新计算。',[],existing=True)
    write('tasks-public.json',tasks);write('private-oracle.json',oracles)
    write('protocol.json',{'version':1,'created_after_library_lock':True,'task_order':[t['id'] for t in tasks],'arms':['A','G'],'max_calls_per_task_arm':3,'maximum_formal_requests':72,'optional_ablation_task_ids':['C01','C02'],'ablation_maximum_requests':6,'model':'deepseek-flash','same_public_case_library':True,'same_tools_and_budgets':True,'factor':'G enforces selected-parent physical locks; A receives the same parent and constraints, with violations graded afterwards. Common model, physics, resources and public recipe contract are identical.','scope':'Local familiar-template adaptation and synthetic state-machine interaction; not unseen external evaluation.','human_participants_added':0,'correct_stop_is_not_design_goal_success':True,'correct_unmet_goal_report_is_not_system_failure':True,'no_score_driven_retries':True})
    print('Library locked first; then 12 tasks created. No numeric/model execution.')
