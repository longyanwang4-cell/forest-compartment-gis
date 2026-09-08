#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
REQ={'XB_ID','XB_NUM','AREA_HA','CTR_LON','CTR_LAT','TREE_SPEC','ORIGIN','AGE_GROUP','CANOPY','LAND_TYPE','BOUND_OK','SURVEY_DT','REMARK','STATUS'}

def first(root,patterns):
    for pat in patterns:
        hits=list(root.rglob(pat))
        if hits:return hits[0]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True);ap.add_argument('--report');a=ap.parse_args();root=Path(a.project).resolve();checks=[];errors=[];warnings=[]
    for label,pats in [('原始影像',['*full*.tif','*原始*.tif']),('裁剪影像',['*clip*.tif','*裁剪*.tif'])]:
        p=first(root,pats);checks.append({'item':label,'ok':bool(p),'path':str(p) if p else None});
        if not p:errors.append('缺少'+label)
    gpkg=first(root,['forest_compartments.gpkg','*.gpkg']);shp=first(root,['xiaoban_preliminary.shp']);gdb=next(iter(root.rglob('*.gdb')),None);db=gpkg or shp or gdb;checks.append({'item':'空间数据库/小班','ok':bool(db),'path':str(db) if db else None})
    if not db:errors.append('缺少小班成果')
    if gpkg or shp:
        try:
            import geopandas as gpd
            import fiona
            x=gpd.read_file(gpkg,layer='xiaoban_preliminary') if gpkg else gpd.read_file(shp);invalid=int((~x.geometry.is_valid).sum());dup=int(x['XB_ID'].duplicated().sum()) if 'XB_ID' in x else None;missing=sorted(REQ-set(x.columns));overlap=0.0
            for i,g in enumerate(x.geometry):
                if i+1<len(x):overlap += float(x.geometry.iloc[i+1:].intersection(g).area.sum())
            checks += [{'item':'小班数量','ok':len(x)>0,'value':len(x)},{'item':'几何有效','ok':invalid==0,'invalid':invalid},{'item':'编号唯一','ok':dup==0,'duplicates':dup},{'item':'字段完整','ok':not missing,'missing':missing},{'item':'重叠面积','ok':overlap<1.0,'square_metres':overlap}]
            if invalid:errors.append(f'{invalid}个无效几何')
            if dup:errors.append(f'{dup}个重复编号')
            if missing:errors.append('缺少字段: '+','.join(missing))
            if overlap>=1.0:errors.append('存在明显重叠')
        except Exception as e:errors.append('深入检查失败: '+str(e))
    bad=[]
    for p in root.rglob('*'):
        if p.is_file() and p.suffix.lower() in {'.json','.md','.txt','.py','.pyt','.ps1'} and p.stat().st_size<2_000_000:
            try:
                if re.search(r'[A-Za-z]:\\Users\\[^\\]+',p.read_text(encoding='utf-8',errors='ignore')):bad.append(str(p))
            except Exception:pass
    checks.append({'item':'无固定用户路径','ok':not bad,'files':bad})
    if bad:warnings.append('发现可能的固定用户路径')
    result={'project':str(root),'ok':not errors,'errors':errors,'warnings':warnings,'checks':checks};text=json.dumps(result,ensure_ascii=False,indent=2);print(text)
    if a.report:Path(a.report).write_text(text,encoding='utf-8')
    raise SystemExit(0 if not errors else 2)
if __name__=='__main__':main()
