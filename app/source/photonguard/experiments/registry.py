"""Public, fixed tool registry; input cannot select Python modules or code."""
TOOLS=[
 {'id':'film','title':'薄膜光谱与选型','description':'TMM有限候选扫描，再对最多2个候选作完整Meep复核。'},
 {'id':'diffraction','title':'衍射与干涉','description':'理想透镜傅里叶焦平面中的单缝/双缝二维光强。'},
 {'id':'gaussian','title':'高斯光束聚焦','description':'已知束腰的理想高斯光束、薄透镜和屏幕光斑比较。'},
]

def evaluate(domain,parameters,output_dir=None):
    if domain not in {x['id'] for x in TOOLS}:raise ValueError('Unknown registered optical tool')
    from .optics import evaluate as run
    return run(domain,parameters,output_dir=output_dir)
