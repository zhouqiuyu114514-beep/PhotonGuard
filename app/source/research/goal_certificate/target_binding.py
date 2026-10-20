"""No implementation yet proves the production-selected mode's continuous rank."""
from photonguard.research_phase_bounds import assess_neff_goal_envelope

def assess(model,pump_result,count_result,rank_claim=None,*,goal):
    # Source/replay statuses are context, not a substitute for a mode certificate.
    # No caller-created Boolean, hash, integer band, or overlap record implements
    # a continuous spectral projection / rank proof.
    expected={'process':'SHG','pump_wavelength_um':1.55,'length_um':1000,'poling_period_um':20,'qpm_order':1,'target_phase_factor_min':.8}
    if goal!=expected or model['task']['requirements']['wavelengths_um']!=[1.55,.775]:raise ValueError('LOCKED_GOAL_BINDING')
    conditional=assess_neff_goal_envelope([0,2.0500000000000003],[2.09,3],goal['pump_wavelength_um'],goal['poling_period_um'],goal['length_um'],goal['target_phase_factor_min'],
        {'bounds_scope':'Pump bound plus hypothetical binding of selected SH mode to verified low spectral branches',
         'selected_SH_rank_certified':False,'caller_rank_claim_not_a_certificate':rank_claim is not None})
    return {'status':'TARGET_MODE_RANK_UNBOUND','design_exclusion_status':'CONDITIONAL_EXCLUSION_UNPROVEN',
       'pump_subresult_status':pump_result.get('status'),'spectral_count_subresult_status':count_result.get('status'),
       'goal_excluded_for_original_target':False,'production_QPM':'INCONCLUSIVE','production_design':'NOT_EVALUATED',
       'production_selection':'Ex fraction >0.55, core energy >0.35, outer energy <0.05, neff>1.44, then maximum neff within find_k returned candidates for bands 1..4; not a permanent band3 specification',
       'missing':['Continuous target spectral rank or qualifying-mode existence with certified polarization/localization AND membership in the four returned production candidates'],
       'conditional_algebra':conditional,'rank_claim_accepted':False,'new_API_calls':0,'production_changed':False}
