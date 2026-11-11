import {useState} from 'react';
import {Button,Card,Collapse,Spin,Space,Upload} from 'antd';
import {LoadingImage} from './LoadingImage';
import {AssetManager} from './AssetManager';
import type {Project,Asset,Work} from '../services/models';

export function ImportStep({project,asset,busy,work,upload,refresh,info}:{project:Project|null;asset:Asset|null;busy:boolean;work:Work;upload:(file:File,world?:File,crs?:File)=>Promise<void>;refresh:()=>Promise<void>;info:(message:string)=>void}){
 const [world,setWorld]=useState<File>(),[crs,setCrs]=useState<File>();
 return <section className="import-step" aria-label="原图导入">
  <Card className="upload-card" title="上传原图" extra={project?.project_name}>
   <Collapse ghost items={[{key:"geo",label:"外部配准文件（可选）",children:<Space wrap><Upload accept=".wld,.tfw,.jgw,.pgw,.gfw,.bpw,.j2w,.txt" maxCount={1} beforeUpload={file=>{setWorld(file);return false;}} onRemove={()=>setWorld(undefined)}><Button disabled={busy}>选择 World 文件</Button></Upload><Upload accept=".prj,.wkt,.txt" maxCount={1} beforeUpload={file=>{setCrs(file);return false;}} onRemove={()=>setCrs(undefined)}><Button disabled={busy}>选择 CRS 文件</Button></Upload><span>两份文件需同时提供，再上传原图。</span></Space>}]}/>
   <Upload.Dragger accept=".png,.jpg,.jpeg,.tif,.tiff,.pdf,.bmp,.webp,.jp2" multiple={false} disabled={busy} showUploadList={false} beforeUpload={file=>{void work(()=>upload(file,world,crs));return false;}}>
    <div className="upload-symbol">{busy?<Spin/>:<svg width="36" height="36" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M6 20v6h20v-6M16 22V5m-6 6 6-6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>}</div>
    <p className="upload-title">{busy?'正在导入，请稍候…':project?'点击或拖入文件，创建另一个项目':'点击选择原图，或将文件拖到这里'}</p>
    <p className="upload-hint">支持 PNG、JPG、TIFF、PDF、BMP、WEBP、JP2</p>
    <span className="upload-select">选择文件</span>
    <p className="upload-note">上传后自动以文件名创建项目 · 保留原始文件</p>
   </Upload.Dragger>
  </Card>
  {project&&<AssetManager key={project.project_id} project={project} busy={busy} work={work} refresh={refresh} info={info}/>}
  {project&&asset&&<Card title="原图预览" className="original-card" extra={<span>{asset.width_px} × {asset.height_px} 像素 · 100%</span>}>
   <div className="original-preview"><LoadingImage key={asset.asset_id} alt="原图预览" src={'/api/projects/'+project.project_id+'/assets/'+asset.asset_id+'/raster'} width={asset.width_px} height={asset.height_px}/></div>
   <p className="original-note">按原始像素尺寸完整展开，超出宽度时可横向滚动。{asset.normalization_config.decoder==='pdfium'?'PDF 显示当前页按指定 DPI 渲染的图像。':''}</p>
  </Card>}
 </section>;
}
