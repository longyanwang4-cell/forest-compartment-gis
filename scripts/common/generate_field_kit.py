#!/usr/bin/env python3
"""Generate neutral field forms and validation metadata without requiring a mobile platform."""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path

FORMS = {
    '小班核查表.csv': ['RECORD_UUID','CHECK_ID','XB_ID','CHECK_TYPE','RESULT','CHECK_DATE','PHOTO_NO','REMARK'],
    '照片点表.csv': ['RECORD_UUID','PHOTO_ID','XB_ID','PHOTO_FILE','DIRECTION','CHECK_DATE','REMARK'],
    '边界调整表.csv': ['RECORD_UUID','ADJ_ID','XB_ID_L','XB_ID_R','ADJ_TYPE','CHECK_DATE','REMARK'],
    '控制样地表.csv': ['RECORD_UUID','PLOT_ID','XB_ID','PLOT_TYPE','RADIUS_M','AREA_M2','SURVEY_DT','REMARK'],
    '两步路轨迹导入登记.csv': ['RECORD_UUID','TRACK_ID','TRACK_NAME','SOURCE_FILE','IMPORT_TIME','REMARK'],
}

SCHEMA = {
    'schema_version': '1.0',
    'purpose': '森林经理学实习外业核查中性字段模板；可用于Excel、QField、Field Maps或Open Foris二次配置。',
    'identifier_policy': '所有记录使用稳定ID；跨设备同步时推荐UUID，不依赖行号或fid。',
    'forms': {
        name: {
            'required_fields': ['RECORD_UUID', fields[1]],
            'fields': fields,
            'constraints': {
                'RECORD_UUID': {'type': 'uuid', 'required': True, 'unique': True},
                fields[1]: {'type': 'text', 'required': True, 'unique': True},
                'XB_ID': {'type': 'text', 'pattern': '^XB[0-9]+$', 'required': False} if 'XB_ID' in fields else None,
            },
        } for name, fields in FORMS.items()
    },
}
for form in SCHEMA['forms'].values():
    form['constraints'] = {k:v for k,v in form['constraints'].items() if v is not None}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    for name, fields in FORMS.items():
        with (out/name).open('w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow(fields)
    (out/'field_form_schema.json').write_text(json.dumps(SCHEMA, ensure_ascii=False, indent=2), encoding='utf-8')
    (out/'README_外业模板.md').write_text(
        '# 外业数据模板\n\n这些文件是中性模板，不自动上传云端，也不代表已完成QField或ArcGIS Field Maps项目配置。'
        '建议外业前由老师确认字段、枚举值和必填规则。跨设备同步应优先使用UUID。\n', encoding='utf-8')
    print(json.dumps({'status':'SUCCESS','output':str(out),'files':sorted(p.name for p in out.iterdir())}, ensure_ascii=False))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
