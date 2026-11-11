"""Baseline-compatible risk routing; automatic decisions never create human review events."""
import json

from mapvector.application.ports import load_feature,restore_feature


def text_decision(feature,candidate,threshold=.90,risk_reasons=None,geometry_reasons=None):
    """OCR score is model evidence, never a calibrated probability or human review."""
    import re

    reasons=list(risk_reasons or [])
    text=feature['text_value'];score=candidate['score'] if candidate else None
    if score is None:reasons.append('no_ocr_evidence')
    elif score<threshold:reasons.append('low_ocr_score')
    if not text.strip():reasons.append('empty_text')
    reasons.extend(geometry_reasons or [])
    if any(run.get('review_required') for run in feature.get('layout_runs',[])):reasons.append('script_position_uncertain')
    if any(run.get('script') in ('subscript','superscript') for run in feature.get('layout_runs',[])) or any(char in '⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉' for char in text) or re.search(r'[A-Za-zЄϵ][0-9]|[0-9][A-Za-z]',text):reasons.append('sub_or_superscript')
    code_prefix=re.match(r'^(?:Ar|Pt|Pz|Mz|Kz|Cmb|[ЄϵOSDCPTJKNZQEЯƐγδλνπξβμρσφχψωατ])',text)
    code_shaped=bool(re.fullmatch(r"[A-Za-zЄϵЯƐγδλνπξβμρσφχψωατ0-9₀-₉′'−—-]{1,8}",text))
    if code_prefix and code_shaped and (len(text)<=4 or any(not char.isalpha() for char in text)):reasons.append('stratigraphic_or_lithology_code')
    safe_punctuation=set("-—·.,、()（）:：'\"°′″/\\ ")
    if any(not ('一'<=char<='鿿' or char.isascii() and char.isalnum() or char.isspace() or char in safe_punctuation) for char in text):reasons.append('special_symbol')
    if re.fullmatch(r'[0-9]{1,3}',text):reasons.append('numeric_or_short')
    if re.search(r'[0-9]\s*[°′″]',text):reasons.append('orientation_measurement')
    if abs(feature.get('rotation_deg',0))>15:reasons.append('soft:rotated_or_vertical')
    rules=json.loads(candidate['rule_suggestions']) if candidate and isinstance(candidate['rule_suggestions'],str) else candidate.get('rule_suggestions',[]) if candidate else []
    if any('OCR_ENGINE_DISAGREEMENT' in rule.get('reason_codes',[]) for rule in rules):reasons.append('ocr_engine_disagreement')
    if candidate and feature['text_value'].strip()!=candidate['raw_text'].strip():reasons.append('text_changed_from_ocr')
    reasons=list(dict.fromkeys(reasons))
    required=any(not reason.startswith('soft:') for reason in reasons)
    return {'review_status':'required' if required else 'auto_accepted_unverified','review_basis':'automatic_rule','review_reason_codes':reasons,'reviewed_at':None,'reviewer_id':None,'reviewed_content_revision':None}


def route_adopted_text(connection,feature_id,threshold=.90,geometry_reasons=None):
    feature=load_feature(connection,feature_id)
    candidate=connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=?',(feature['primary_candidate_id'],)).fetchone() if feature['primary_candidate_id'] else None
    decision=text_decision(feature,dict(candidate) if candidate else None,threshold,geometry_reasons=geometry_reasons)
    connection.execute('UPDATE text_attribute SET review_status=?,review_basis=?,review_reason_codes=?,reviewed_at=NULL,reviewer_id=NULL,reviewed_content_revision=NULL WHERE feature_id=?',(decision['review_status'],decision['review_basis'],json.dumps(decision['review_reason_codes']),feature_id))
    return decision


def classify(connection,project_id,command,timestamp):
    asset=connection.execute('SELECT * FROM asset WHERE asset_id=? AND project_id=?',(command.asset_id,project_id)).fetchone()
    features=[load_feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' ORDER BY feature_id",(project_id,command.asset_id))]
    changes=[]
    for feature in features:
        if feature['review_status'] in ('confirmed','manual_edited','pipeline_complete_unverified','skipped') or feature['source_type']=='manual':continue
        candidate=connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=? AND text_feature_id=?',(feature['primary_candidate_id'],feature['feature_id'])).fetchone() if feature['primary_candidate_id'] else None
        if command.candidate_only and candidate is None:continue
        decision=text_decision(feature,dict(candidate) if candidate else None,command.threshold)
        updated={**feature,**decision,'revision':command.base_revision+1,'updated_at':timestamp}
        restore_feature(connection,updated);changes.append((feature,updated))
    return changes
