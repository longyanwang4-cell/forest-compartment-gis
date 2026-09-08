# -*- coding: utf-8 -*-
import argparse,json,os,shutil,math,time,uuid
from pathlib import Path
import arcpy

def _is_reparse_or_link(path):
    p = Path(path).expanduser().absolute()
    try:
        if p.is_symlink():
            return True
        st = p.lstat()
        return bool(getattr(st, 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True

def _assert_no_link_components(path):
    p = Path(path).expanduser().absolute()
    parts = p.parts
    cur = Path(parts[0])
    for part in parts[1:]:
        cur = cur / part
        if not cur.exists() and not cur.is_symlink():
            continue
        if _is_reparse_or_link(cur):
            raise RuntimeError('路径包含符号链接或重解析点: '+str(cur))
    return p

def _assert_safe_dataset_companions(path):
    p = Path(path).expanduser().absolute()
    if p.suffix.lower() == '.vrt':
        raise RuntimeError('出于安全考虑，当前版本不接受VRT；请转换为本地GeoTIFF')
    candidates=[]
    if p.suffix.lower() == '.shp':
        candidates=list(p.parent.glob(p.stem + '.*'))
    elif p.suffix.lower() in ('.tif','.tiff','.img','.jp2'):
        candidates=[Path(str(p)+x) for x in ('.aux.xml','.ovr','.xml')]
        candidates += [p.with_suffix(x) for x in ('.tfw','.tifw','.wld')]
    for c in candidates:
        if not c.exists() and not c.is_symlink():
            continue
        _assert_no_link_components(c)
        if not c.resolve().is_file():
            raise RuntimeError('GIS伴随文件不是普通文件: '+str(c))

def _is_within(child, parent):
    try:
        return os.path.commonpath([str(Path(child).resolve()), str(Path(parent).resolve())]) == str(Path(parent).resolve())
    except ValueError:
        return False

def _validate_path_safety(cfg, out):
    inputs=[]
    for value in list((cfg.get('input') or {}).values()) + [cfg.get('preliminary_compartments')]:
        if value:
            raw=_assert_no_link_components(value)
            p=raw.resolve()
            if not p.exists() or not p.is_file(): raise RuntimeError('输入文件不存在或不是普通文件: '+str(p))
            _assert_safe_dataset_companions(raw)
            inputs.append(p)
    raw_out=_assert_no_link_components(out)
    out=raw_out.resolve()
    for item in inputs:
        parent=item.parent
        if out == parent or _is_within(out,parent) or _is_within(parent,out):
            raise RuntimeError('输入与输出目录不能相同或相互嵌套: input='+str(parent)+' output='+str(out))
    return out

FIELDS=[('RECORD_UUID','TEXT',36),('XB_ID','TEXT',20),('XB_NUM','LONG',None),('AREA_HA','DOUBLE',None),('CTR_LON','DOUBLE',None),('CTR_LAT','DOUBLE',None),('ELEV_M','DOUBLE',None),('SLOPE_DEG','DOUBLE',None),('AUTO_CLAS','TEXT',40),('CHK_PRI','TEXT',20),('TREE_SPEC','TEXT',80),('ORIGIN','TEXT',40),('AGE_GROUP','TEXT',40),('CANOPY','DOUBLE',None),('LAND_TYPE','TEXT',40),('BOUND_OK','TEXT',40),('SURVEY_DT','TEXT',30),('REMARK','TEXT',255),('STATUS','TEXT',20)]
def sr_auto(boundary):
 wgs=arcpy.SpatialReference(4326)
 with arcpy.da.SearchCursor(boundary,['SHAPE@']) as c:g=next(c)[0].projectAs(wgs)
 p=g.centroid;zone=int((p.X+180)//6)+1;return arcpy.SpatialReference((32600 if p.Y>=0 else 32700)+zone)
def spatial_reference_from_config(value):
 if isinstance(value,str) and value.upper().startswith('EPSG:'):
  return arcpy.SpatialReference(int(value.split(':',1)[1]))
 return arcpy.SpatialReference(value)
def copy_project(src,out,sr):
 d=arcpy.Describe(src);return arcpy.management.Project(src,out,sr)[0] if d.spatialReference.factoryCode!=sr.factoryCode else arcpy.management.CopyFeatures(src,out)[0]
def fields(fc):
 e={f.name.upper() for f in arcpy.ListFields(fc)}
 for n,t,l in FIELDS:
  if n not in e:arcpy.management.AddField(fc,n,t,field_length=l if l else None)
def empty(gdb,name,geom,sr,fs):
 fc=os.path.join(gdb,name)
 if not arcpy.Exists(fc):arcpy.management.CreateFeatureclass(gdb,name,geom,spatial_reference=sr)
 ex={f.name.upper() for f in arcpy.ListFields(fc)}
 for n,t,l in fs:
  if n not in ex:arcpy.management.AddField(fc,n,t,field_length=l if l else None)
 return fc

def related_files(path):
    p = Path(path)
    if p.suffix.lower() == '.shp':
        return sorted(p.parent.glob(p.stem + '.*'))
    files = [p]
    for e in ['.tfw', '.aux.xml', '.ovr', '.xml']:
        c = Path(str(p) + e)
        if c.exists():
            files.append(c)
    return files

def snapshot(inputs):
    snap = {}
    for k, v in inputs.items():
        if not v:
            continue
        for f in related_files(v):
            if f.exists():
                st = f.stat()
                snap[str(f)] = {'size': st.st_size, 'mtime_ns': st.st_mtime_ns}
    return snap

def read_zone_mean(tbl):
    m = {}
    with arcpy.da.SearchCursor(tbl, ['XB_ID', 'MEAN']) as c:
        for z, mn in c:
            m[z] = mn
    return m

def compute_terrain(cfg, xfc, dem_clip, gdb, out, sr, inputs):
    terrain = cfg.get('terrain', {}) or {}
    dem_z_unit = terrain.get('dem_z_unit')
    z_factor = terrain.get('z_factor')
    cell_size = terrain.get('dem_cell_size')
    expected = cfg.get('expected_compartment_count')
    rep = {'status': 'IN_PROGRESS', 'error_type': None, 'error_message': None,
           'dem_path': None, 'dem_crs': None, 'dem_linear_unit': None,
           'dem_z_unit': dem_z_unit, 'dem_z_unit_source': 'config',
           'z_factor': z_factor, 'z_factor_source': 'config',
           'slope_unit': 'DEGREE', 'stat_method': 'ZonalStatisticsAsTable MEAN (ignore_nodata=DATA)',
           'spatial_analyst': None, 'expected_compartment_count': expected,
           'dem_cell_size_config': cell_size, 'dem_cell_size_actual': None,
           'stage_seconds': {}, 'per_compartment': [], 'null_records': [], 'checks': {}}
    pre = snapshot(inputs)
    license_ok = False
    try:
        if arcpy.CheckExtension('Spatial') != 'Available':
            raise RuntimeError('Spatial Analyst 许可不可用，无法计算 ELEV_M/SLOPE_DEG，已停止 build-data（不安装/修复环境）。')
        ret = arcpy.CheckOutExtension('Spatial')
        if str(ret) != 'CheckedOut':
            raise RuntimeError('CheckOutExtension(Spatial) 未成功，返回: %s' % ret)
        license_ok = True
        rep['spatial_analyst'] = 'CheckedOut'
        if not sr.linearUnitName.lower().startswith('met'):
            raise RuntimeError('工作坐标系线性单位为 %s（非米），无法用 z_factor=%s 计算坡度。' % (sr.linearUnitName, z_factor))
        if z_factor is None:
            raise RuntimeError('配置缺少 terrain.z_factor。')
        t = time.time()
        dem_proj = str(out/'Data'/'DEM'/('dem_%d.tif' % sr.factoryCode))
        if arcpy.Describe(dem_clip).spatialReference.factoryCode != sr.factoryCode:
            kw = {'in_raster': dem_clip, 'out_raster': dem_proj,
                  'out_coor_system': sr, 'resampling_type': 'BILINEAR'}
            if cell_size:
                kw['cell_size'] = cell_size
            arcpy.management.ProjectRaster(**kw)
        else:
            dem_proj = dem_clip
        rep['stage_seconds']['dem_project'] = round(time.time()-t, 3)
        dd = arcpy.Describe(dem_proj)
        rep['dem_path'] = dem_proj
        rep['dem_crs'] = 'EPSG:%d' % dd.spatialReference.factoryCode
        rep['dem_linear_unit'] = dd.spatialReference.linearUnitName
        rep['dem_cell_size_actual'] = {'meanCellWidth': dd.meanCellWidth, 'meanCellHeight': dd.meanCellHeight}
        rep['dem_range'] = {'min': float(arcpy.GetRasterProperties_management(dem_proj, 'MINIMUM').getOutput(0)),
                            'max': float(arcpy.GetRasterProperties_management(dem_proj, 'MAXIMUM').getOutput(0))}
        with arcpy.EnvManager(outputCoordinateSystem=sr, snapRaster=dem_proj, cellSize=dem_proj, extent=dem_proj, mask=dem_proj):
            t = time.time()
            elev_tbl = os.path.join(gdb, 'Elevation_Stats')
            arcpy.sa.ZonalStatisticsAsTable(xfc, 'XB_ID', dem_proj, elev_tbl, 'DATA', 'MEAN')
            elev_map = read_zone_mean(elev_tbl)
            rep['stage_seconds']['elev_stats'] = round(time.time()-t, 3)
            t = time.time()
            slope_ras = arcpy.sa.Slope(dem_proj, 'DEGREE', float(z_factor), 'PLANAR')
            slope_tif = str(out/'Data'/'DEM'/'slope_deg.tif')
            slope_ras.save(slope_tif)
            del slope_ras
            slope_tbl = os.path.join(gdb, 'Slope_Stats')
            arcpy.sa.ZonalStatisticsAsTable(xfc, 'XB_ID', slope_tif, slope_tbl, 'DATA', 'MEAN')
            slope_map = read_zone_mean(slope_tbl)
            rep['stage_seconds']['slope_stats'] = round(time.time()-t, 3)
        rep['stats_tables'] = {'elevation': elev_tbl, 'slope': slope_tbl,
                               'elevation_rows': int(arcpy.GetCount_management(elev_tbl).getOutput(0)),
                               'slope_rows': int(arcpy.GetCount_management(slope_tbl).getOutput(0))}
        t = time.time()
        per = []
        nulls = []
        with arcpy.da.UpdateCursor(xfc, ['XB_ID', 'ELEV_M', 'SLOPE_DEG', 'REMARK']) as cur:
            for xbid, elev, slope, remark in cur:
                e = elev_map.get(xbid)
                s = slope_map.get(xbid)
                nr = remark
                if e is None or s is None:
                    tag = 'DEM_NO_DATA'
                    if not remark or tag not in remark:
                        nr = (remark+';' if remark else '') + tag
                    nulls.append({'xb_id': xbid, 'reason': tag})
                cur.updateRow([xbid, e, s, nr])
                per.append({'xb_id': xbid, 'elev_m': e, 'slope_deg': s})
        rep['stage_seconds']['writeback'] = round(time.time()-t, 3)
        rep['per_compartment'] = per
        rep['null_records'] = nulls
        rep['status'] = 'SUCCESS_WITH_WARNINGS' if nulls else 'SUCCESS'
    except Exception as ex:
        rep['status'] = 'FAILED'
        rep['error_type'] = type(ex).__name__
        rep['error_message'] = str(ex)
        (out/'terrain_statistics_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
    finally:
        # 本机 ArcGIS Pro 3.5.3 的 arcpy.CheckInExtension('Spatial') 会触发 0xC0000005 原生崩溃
        # （已用不含任何业务对象的最小脚本验证，与本代码/栅格对象无关）。故不调用；
        # Spatial Analyst 许可随 propy 进程退出自动释放，省略 CheckIn 是安全的。
        if license_ok:
            rep['spatial_analyst_checkin'] = ('skipped: arcpy.CheckInExtension triggers 0xC0000005 '
                                              'access violation in this environment; license is '
                                              'auto-released when the propy process exits')
    post = snapshot(inputs)
    integ = {}
    for f, bs in pre.items():
        af = post.get(f)
        integ[f] = {'size_before': bs['size'], 'size_after': (af['size'] if af else None),
                    'mtime_before': bs['mtime_ns'], 'mtime_after': (af['mtime_ns'] if af else None),
                    'unchanged': bool(af and af['size'] == bs['size'] and af['mtime_ns'] == bs['mtime_ns'])}
    rep['input_integrity'] = integ
    ev = [p['elev_m'] for p in per if p['elev_m'] is not None]
    sl = [p['slope_deg'] for p in per if p['slope_deg'] is not None]
    dmin = rep['dem_range']['min']
    dmax = rep['dem_range']['max']
    rep['elev_m'] = {'min': min(ev) if ev else None, 'max': max(ev) if ev else None,
                     'mean': (sum(ev)/len(ev)) if ev else None}
    rep['slope_deg'] = {'min': min(sl) if sl else None, 'max': max(sl) if sl else None,
                        'mean': (sum(sl)/len(sl)) if sl else None}
    rep['compartment_count'] = len(per)
    byid = {p['xb_id']: p for p in per}
    zero_anom = [p['xb_id'] for p in per if p['elev_m'] == 0] if dmin > 0 else []
    rep['checks'] = {
        'count_matches_expected': (len(per) == expected) if expected else None,
        'expected_compartment_count': expected,
        'stats_tables_written': rep['stats_tables']['elevation_rows'] > 0 and rep['stats_tables']['slope_rows'] > 0,
        'elev_within_dem_range': all(dmin-1 <= v <= dmax+1 for v in ev) if ev else False,
        'elev_zero_anomaly_only_if_dem_min_gt0': zero_anom,
        'slope_within_0_90': all(0 <= v <= 90 for v in sl) if sl else False,
        'null_count': len(nulls),
        'xb07': byid.get('XB07'), 'xb09': byid.get('XB09'),
        'inputs_unchanged': all(v['unchanged'] for v in integ.values())}
    (out/'terrain_statistics_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    return rep

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);a=ap.parse_args();cfg=json.loads(Path(a.config).read_text(encoding='utf-8-sig'));out=_validate_path_safety(cfg,Path(cfg['output_dir']))
 if out.exists() and any(out.iterdir()) and not cfg.get('allow_existing_output',False):raise RuntimeError('输出目录非空，为防覆盖已停止: '+str(out))
 for d in ['Data/DEM','Tools','Docs','Imports','Backups']: (out/d).mkdir(parents=True,exist_ok=True)
 (out/'_BUILD_INCOMPLETE.json').write_text(json.dumps({'status':'IN_PROGRESS','started':time.time()},ensure_ascii=False),encoding='utf-8')
 image=cfg['input']['imagery'];bound=cfg['input']['boundary'];dem=cfg['input'].get('dem');xb=cfg.get('preliminary_compartments');sr=sr_auto(bound) if cfg.get('working_crs','auto_utm')=='auto_utm' else spatial_reference_from_config(cfg['working_crs'])
 gdb=str(out/'ProjectData.gdb')
 if not arcpy.Exists(gdb):arcpy.management.CreateFileGDB(str(out),'ProjectData.gdb')
 arcpy.management.CopyRaster(image,str(out/'Data'/'imagery_full.tif'));arcpy.management.Clip(image,'#',str(out/'Data'/'imagery_clip.tif'),bound,'#','ClippingGeometry','MAINTAIN_EXTENT')
 if dem:
  arcpy.management.CopyRaster(dem,str(out/'Data'/'DEM'/'dem_full.tif'));arcpy.management.Clip(dem,'#',str(out/'Data'/'DEM'/'dem_clip.tif'),bound,'#','ClippingGeometry','MAINTAIN_EXTENT')
 copy_project(bound,os.path.join(gdb,'Work_Boundary'),sr)
 if not xb:raise RuntimeError('缺少preliminary_compartments，请先运行候选区划或提供已有小班')
 xfc=copy_project(xb,os.path.join(gdb,'Xiaoban_Preliminary'),sr);fields(xfc)
 wgs=arcpy.SpatialReference(4326)
 with arcpy.da.UpdateCursor(xfc,['SHAPE@','RECORD_UUID','AREA_HA','CTR_LON','CTR_LAT','STATUS']) as cur:
  for geom,record_uuid,area,lon,lat,status in cur:
   p=geom.projectAs(wgs).labelPoint;cur.updateRow([geom,record_uuid or str(uuid.uuid4()),geom.getArea('GEODESIC','HECTARES'),p.X,p.Y,status or 'PRELIMINARY'])
 if dem: compute_terrain(cfg,xfc,str(out/'Data'/'DEM'/'dem_clip.tif'),gdb,out,sr,{'imagery':image,'boundary':bound,'dem':dem,'preliminary_compartments':xb})
 arcpy.management.FeatureToPoint(xfc,os.path.join(gdb,'Xiaoban_Centers'),'INSIDE')
 empty(gdb,'TwoSteps_Track_Lines','POLYLINE',sr,[('RECORD_UUID','TEXT',36),('TRACK_ID','TEXT',50),('TRACK_NAME','TEXT',100),('SOURCE_FILE','TEXT',255),('IMPORT_TIME','TEXT',30),('REMARK','TEXT',255)])
 empty(gdb,'TwoSteps_Track_Points','POINT',sr,[('RECORD_UUID','TEXT',36),('POINT_ID','TEXT',50),('POINT_TYPE','TEXT',50),('SOURCE_FILE','TEXT',255),('IMPORT_TIME','TEXT',30),('REMARK','TEXT',255)])
 empty(gdb,'Field_Check_Points','POINT',sr,[('RECORD_UUID','TEXT',36),('CHECK_ID','TEXT',50),('XB_ID','TEXT',20),('CHECK_TYPE','TEXT',50),('RESULT','TEXT',255),('CHECK_DATE','TEXT',30),('PHOTO_NO','TEXT',100),('REMARK','TEXT',255)])
 empty(gdb,'Boundary_Adjustment_Lines','POLYLINE',sr,[('RECORD_UUID','TEXT',36),('ADJ_ID','TEXT',50),('XB_ID_L','TEXT',20),('XB_ID_R','TEXT',20),('ADJ_TYPE','TEXT',50),('CHECK_DATE','TEXT',30),('REMARK','TEXT',255)])
 empty(gdb,'Photo_Points','POINT',sr,[('RECORD_UUID','TEXT',36),('PHOTO_ID','TEXT',50),('XB_ID','TEXT',20),('PHOTO_FILE','TEXT',255),('DIRECTION','DOUBLE',None),('CHECK_DATE','TEXT',30),('REMARK','TEXT',255)])
 empty(gdb,'Control_Plot_Centers','POINT',sr,[('RECORD_UUID','TEXT',36),('PLOT_ID','TEXT',50),('XB_ID','TEXT',20),('PLOT_TYPE','TEXT',50),('RADIUS_M','DOUBLE',None),('AREA_M2','DOUBLE',None),('SURVEY_DT','TEXT',30),('REMARK','TEXT',255)])
 empty(gdb,'Standard_Plot_Polygons','POLYGON',sr,[('RECORD_UUID','TEXT',36),('PLOT_ID','TEXT',50),('XB_ID','TEXT',20),('PLOT_TYPE','TEXT',50),('AREA_M2','DOUBLE',None),('SURVEY_DT','TEXT',30),('REMARK','TEXT',255)])
 src=Path(__file__).with_name('ForestCompartmentPro35.pyt');shutil.copy2(src,out/'Tools'/'ForestCompartmentPro35.pyt')
 (out/'Docs'/'开始使用.txt').write_text('数据处理完成。下一步请选择新建ArcGIS Pro项目、打开已有项目或暂不操作。项目创建后使用Tools\\ForestCompartmentPro35.pyt进行影像切换、轨迹导入、面积更新和自检。',encoding='utf-8')
 sent=out/'_BUILD_INCOMPLETE.json'
 if sent.exists(): sent.unlink()
 print(out)
if __name__=='__main__':main()
