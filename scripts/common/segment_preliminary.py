#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,re,sys
from pathlib import Path
import numpy as np, geopandas as gpd, rasterio
from rasterio.mask import mask
from rasterio.warp import reproject,Resampling
from rasterio.features import shapes, geometry_window
from shapely.geometry import mapping,shape,Polygon,MultiPolygon
from shapely.validation import make_valid
from scipy import ndimage as ndi
from scipy.sparse import coo_matrix
from skimage.segmentation import slic
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import StandardScaler
from pyproj import CRS, Transformer, Geod

SKILL_ROOT = Path(__file__).resolve().parents[2]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
from forestgis_core.path_safety import PathSafetyError, assert_no_link_components, assert_safe_dataset_companions, ensure_disjoint_roots

def pixel_resolution_metres(crs_value, transform, width, height):
    """返回像元X/Y方向分辨率（米），同时说明换算方法。"""
    crs = CRS.from_user_input(crs_value)
    dx_native = math.hypot(transform.a, transform.d)
    dy_native = math.hypot(transform.b, transform.e)
    if crs.is_projected:
        factor = 1.0
        unit_name = "unknown"
        if crs.axis_info:
            factor = float(crs.axis_info[0].unit_conversion_factor or 1.0)
            unit_name = str(crs.axis_info[0].unit_name or "unknown")
        return dx_native * factor, dy_native * factor, {
            "method": "projected_linear_unit",
            "native_unit": unit_name,
            "unit_to_metre_factor": factor,
        }
    if crs.is_geographic:
        cx = max(0.5, width / 2.0)
        cy = max(0.5, height / 2.0)
        x0, y0 = transform * (cx, cy)
        x1, y1 = transform * (cx + 1.0, cy)
        x2, y2 = transform * (cx, cy + 1.0)
        transformer = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
        lon0, lat0 = transformer.transform(x0, y0)
        lon1, lat1 = transformer.transform(x1, y1)
        lon2, lat2 = transformer.transform(x2, y2)
        geod = Geod(ellps="WGS84")
        _, _, dx = geod.inv(lon0, lat0, lon1, lat1)
        _, _, dy = geod.inv(lon0, lat0, lon2, lat2)
        return abs(float(dx)), abs(float(dy)), {
            "method": "geodesic_at_raster_centre",
            "native_unit": "degree",
            "unit_to_metre_factor": None,
            "centre_lon_lat": [float(lon0), float(lat0)],
        }
    raise RuntimeError("无法确定影像坐标系的像元米制分辨率: %s" % crs)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);a=ap.parse_args();cfg=json.loads(Path(a.config).read_text(encoding='utf-8-sig'))
    raw_image=Path(cfg['input']['imagery']).expanduser().absolute(); raw_boundary=Path(cfg['input']['boundary']).expanduser().absolute()
    raw_dem=Path(cfg['input']['dem']).expanduser().absolute() if cfg['input'].get('dem') else None
    raw_out=Path(cfg['output_dir']).expanduser().absolute()
    try:
        assert_no_link_components(raw_image); assert_no_link_components(raw_boundary); assert_no_link_components(raw_out)
        if raw_dem: assert_no_link_components(raw_dem)
    except PathSafetyError as exc: raise RuntimeError(str(exc)) from exc
    image=raw_image.resolve(); boundary_path=raw_boundary.resolve(); dem_path=raw_dem.resolve() if raw_dem else None; has_dem=bool(dem_path and dem_path.exists())
    for required in (image,boundary_path):
        if not required.exists() or not required.is_file(): raise RuntimeError('输入文件不存在或不是普通文件: '+str(required))
    if dem_path and (not dem_path.exists() or not dem_path.is_file()): raise RuntimeError('DEM不存在或不是普通文件: '+str(dem_path))
    try:
        assert_safe_dataset_companions(image, image.parent)
        assert_safe_dataset_companions(boundary_path, boundary_path.parent)
        if dem_path: assert_safe_dataset_companions(dem_path, dem_path.parent)
    except PathSafetyError as exc: raise RuntimeError(str(exc)) from exc
    out=raw_out.resolve()
    try:
        ensure_disjoint_roots(image.parent,out); ensure_disjoint_roots(boundary_path.parent,out)
        if dem_path: ensure_disjoint_roots(dem_path.parent,out)
    except PathSafetyError as exc: raise RuntimeError(str(exc)) from exc
    if out.exists() and any(out.iterdir()) and not bool(cfg.get('allow_existing_output',False)):
        raise RuntimeError('输出目录非空，为防覆盖已停止: '+str(out))
    out.mkdir(parents=True,exist_ok=True);seg=cfg.get('segmentation',{})
    ncomp=int(seg.get('candidate_compartments',20)); superpixels=int(seg.get('superpixels',650)); compactness=float(seg.get('compactness',8)); max_pixels=int(seg.get('max_pixels',50_000_000))
    if ncomp < 2: raise RuntimeError('候选小班数量必须至少为2')
    if superpixels < ncomp: raise RuntimeError('superpixels不能小于候选小班数量')
    if compactness <= 0: raise RuntimeError('compactness必须大于0')
    if max_pixels < 1_000_000: raise RuntimeError('max_pixels不能小于1000000')
    boundary=gpd.read_file(boundary_path)[['geometry']]
    if boundary.empty: raise RuntimeError('Bound边界为空')
    if boundary.crs is None:raise RuntimeError('Bound边界缺少坐标系')
    boundary['geometry']=boundary.geometry.apply(make_valid)
    boundary=boundary[~boundary.geometry.is_empty].copy()
    if boundary.empty or not boundary.geom_type.isin(['Polygon','MultiPolygon']).all(): raise RuntimeError('Bound边界必须为非空面要素')
    with rasterio.open(image) as src:
        if src.crs is None: raise RuntimeError('主影像缺少坐标系')
        b=boundary.to_crs(src.crs); bound_geom=mapping(b.geometry.union_all())
        try:
            win=geometry_window(src,[bound_geom])
            requested_pixels=int(win.width)*int(win.height)
        except Exception as exc:
            raise RuntimeError('无法计算Bound对应影像窗口: '+str(exc)) from exc
        if requested_pixels > max_pixels:
            raise RuntimeError(f'作业区影像窗口约{requested_pixels}像元，超过安全上限{max_pixels}；请裁剪影像或提高segmentation.max_pixels')
        arr,tr=mask(src,[bound_geom],crop=True,filled=False,indexes=[1,2,3]);valid=~arr.mask[0]
        if not bool(valid.any()): raise RuntimeError('Bound与主影像没有有效重叠像元')
        raw=np.moveaxis(arr.filled(0),0,-1).astype(np.float32)
        if raw.shape[2]<3:raise RuntimeError('主影像至少需要3个波段')
        raw=raw[:,:,:3];rgb=np.zeros_like(raw)
        stretch=[]
        for band in range(3):
            vals=raw[:,:,band][valid];lo,hi=np.percentile(vals,[2,98]);rgb[:,:,band]=np.clip((raw[:,:,band]-lo)/(hi-lo+1e-6),0,1);stretch.append([float(lo),float(hi)])
        rgb[~valid]=np.mean(rgb[valid],axis=0);h,w=valid.shape;crs=src.crs
        prof=src.profile.copy();prof.update(height=h,width=w,transform=tr,count=min(3,src.count),compress='LZW',tiled=True)
        with rasterio.open(out/'imagery_clip.tif','w',**prof) as dst:dst.write(arr.filled(src.nodata or 0)[:3])
    dem=np.zeros((h,w),dtype=np.float32)
    if has_dem:
        with rasterio.open(dem_path) as ds:
            if ds.crs is None: raise RuntimeError('DEM缺少坐标系')
            dem[:]=np.nan;reproject(rasterio.band(ds,1),dem,src_transform=ds.transform,src_crs=ds.crs,dst_transform=tr,dst_crs=crs,dst_nodata=np.nan,resampling=Resampling.bilinear)
            finite=dem[valid & np.isfinite(dem)]
            if finite.size == 0: raise RuntimeError('DEM在作业区内没有有效高程值')
            dem=np.where(np.isfinite(dem),dem,float(np.nanmedian(finite)))
    xres,yres,resolution_info=pixel_resolution_metres(crs,tr,w,h)
    if not (xres>0 and yres>0):raise RuntimeError('影像像元分辨率换算失败')
    if has_dem:
        dy,dx=np.gradient(dem,yres,xres);slope=np.degrees(np.arctan(np.hypot(dx,dy)))
    else:slope=np.zeros_like(dem)
    gray=.299*rgb[:,:,0]+.587*rgb[:,:,1]+.114*rgb[:,:,2];mean=ndi.gaussian_filter(gray,4);texture=np.sqrt(np.maximum(ndi.gaussian_filter(gray**2,4)-mean**2,0));green=2*rgb[:,:,1]-rgb[:,:,0]-rgb[:,:,2]
    sp=slic(ndi.gaussian_filter(rgb,sigma=(1,1,0)),n_segments=superpixels,compactness=compactness,start_label=1,mask=valid,channel_axis=-1,enforce_connectivity=True,slic_zero=True)
    ids=np.unique(sp[valid]);stack=np.dstack([rgb,texture,green,dem,slope]);features=[];centroids=[]
    for sid in ids:
        m=sp==sid;v=stack[m];yy,xx=np.nonzero(m);features.append(np.r_[v.mean(0),v[:,:3].std(0)]);centroids.append([xx.mean()/w,yy.mean()/h])
    X=StandardScaler().fit_transform(np.asarray(features));X=np.c_[X,np.asarray(centroids)*.65]
    pairs=set()
    for aa,bb in [(sp[:,:-1],sp[:,1:]),(sp[:-1,:],sp[1:,:])]:
        d=(aa!=bb)&(aa>0)&(bb>0)
        for x,y in np.stack([aa[d],bb[d]],1):pairs.add((int(min(x,y)),int(max(x,y))))
    idx={int(s):i for i,s in enumerate(ids)};rows=[];cols=[];data=[]
    for x,y in pairs:
        i,j=idx[x],idx[y];rows += [i,j];cols += [j,i];data += [1,1]
    if len(ids) < ncomp: raise RuntimeError(f'有效超像素数量{len(ids)}小于候选小班数量{ncomp}')
    conn=coo_matrix((data,(rows,cols)),shape=(len(ids),len(ids))).tocsr()
    labels=AgglomerativeClustering(n_clusters=ncomp,linkage='ward',connectivity=conn,compute_full_tree=True).fit_predict(X)+1
    lab=np.zeros_like(sp,dtype=np.int16)
    for sid,cid in zip(ids,labels):lab[sp==sid]=cid
    geoms=[];vals=[]
    for gj,v in shapes(lab,mask=valid,transform=tr):
        if int(v)>0:geoms.append(shape(gj));vals.append(int(v))
    poly=gpd.GeoDataFrame({'cluster':vals},geometry=geoms,crs=crs).dissolve('cluster',as_index=False)
    work=boundary.estimate_utm_crs() if cfg.get('working_crs','auto_utm')=='auto_utm' else cfg['working_crs'];bound=boundary.to_crs(work).geometry.union_all();poly=poly.to_crs(work);poly['geometry']=poly.geometry.apply(make_valid).intersection(bound);poly=poly[~poly.geometry.is_empty].copy().dissolve('cluster',as_index=False)
    leftover=make_valid(bound.difference(poly.geometry.union_all()));parts=[leftover] if isinstance(leftover,Polygon) else list(leftover.geoms) if isinstance(leftover,MultiPolygon) else []
    for s in parts:
        if s.is_empty or s.area<=0:continue
        shared=poly.geometry.boundary.intersection(s.boundary).length;target=shared.idxmax() if float(shared.max())>0 else poly.geometry.distance(s).idxmin();poly.at[target,'geometry']=make_valid(poly.at[target,'geometry'].union(s))
    poly=poly.dissolve('cluster',as_index=False);p=poly.to_crs('EPSG:4326').geometry.representative_point();order=np.lexsort((p.x,-p.y));prefix=str(cfg.get('naming',{}).get('prefix','XB'));start=int(cfg.get('naming',{}).get('start',1))
    if not re.fullmatch(r'[A-Za-z0-9_\u4e00-\u9fff-]{1,12}',prefix): raise RuntimeError('小班编号前缀只能包含字母、数字、下划线、短横线或中文，长度1-12')
    if start < 0: raise RuntimeError('小班编号起始值不能为负数')
    idsout=['']*len(poly)
    for rank,i in enumerate(order,start=start):idsout[i]=f'{prefix}{rank:02d}'
    poly['XB_ID']=idsout;poly['XB_NUM']=[int(x[len(prefix):]) for x in idsout];poly['AREA_HA']=poly.area/10000;rp=poly.geometry.representative_point();rw=gpd.GeoSeries(rp,crs=work).to_crs('EPSG:4326');poly['CTR_LON']=rw.x;poly['CTR_LAT']=rw.y
    poly['ELEV_M']=0.0;poly['SLOPE_DEG']=0.0;poly['AUTO_CLAS']='';poly['CHK_PRI']='MEDIUM'
    for c in ['TREE_SPEC','ORIGIN','AGE_GROUP','LAND_TYPE','BOUND_OK','SURVEY_DT','REMARK']:poly[c]=''
    poly['CANOPY']=np.nan;poly['STATUS']='PRELIMINARY';poly=poly.sort_values('XB_NUM')
    gpkg=out/'forest_compartments.gpkg';poly.to_file(gpkg,layer='xiaoban_preliminary',driver='GPKG');boundary.to_crs(work).to_file(gpkg,layer='work_boundary',driver='GPKG')
    shp=out/'shapefile';shp.mkdir(exist_ok=True);poly.to_file(shp/'xiaoban_preliminary.shp',driver='ESRI Shapefile',encoding='UTF-8');boundary.to_crs(work).to_file(shp/'work_boundary.shp',driver='ESRI Shapefile',encoding='UTF-8')
    report={'candidate_compartments':len(poly),'boundary_area_ha':float(bound.area/10000),'output_area_ha':float(poly.area.sum()/10000),'working_crs':str(work),'imagery_crs':str(crs),'pixel_size_m':{'x':float(xres),'y':float(yres)},'resolution_info':resolution_info,'dem_used':has_dem,'stretch':stretch,'requested_pixels':requested_pixels,'max_pixels':max_pixels,'warning':'自动图面预区划，必须外业核实'}
    (out/'segmentation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
