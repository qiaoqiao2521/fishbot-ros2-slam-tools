#!/usr/bin/env python3
"""Reuse public robot and MIT MetaWorld meshes for an RGB-only object fixture."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
AMCL_PROFILE=dict(sigma_hit=.05,max_beams=180,z_hit=.95,z_rand=.05,
                  update_min_a=.02,update_min_d=.02)
ASSETS = {
    'mug.stl': 'objects/meshes/coffeemachine/mug.stl',
    'handle.stl': 'objects/meshes/coffeemachine/handle.stl',
    **{f'laptop_{part}.stl':f'objects/meshes/laptop/laptop_{part}.stl'
       for part in ('base','keys','screen','top','hinge')},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_assets(source, license_file, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    license_file = Path(license_file).resolve()
    if 'MIT License' not in license_file.read_text():
        raise ValueError('Expected the official MetaWorld MIT license')
    if destination.exists():
        raise FileExistsError('Use a new asset cache; never overwrite source assets')
    if not all((source / name).is_file() for name in ASSETS.values()):
        raise ValueError('Missing official MetaWorld cup/laptop meshes')
    destination.mkdir(parents=True, mode=0o700)
    records = []
    for name, relative in ASSETS.items():
        shutil.copyfile(source / relative, destination / name)
        records.append(dict(file=name, source_path=relative, sha256=sha(destination/name)))
    shutil.copyfile(license_file, destination/'LICENSE-MetaWorld')
    manifest = dict(provider='Farama-Foundation/Metaworld', version='3.0.0', license='MIT',
        source='https://github.com/Farama-Foundation/Metaworld', files=records,
        license_sha256=sha(destination/'LICENSE-MetaWorld'))
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def build_scene(assets, destination, share=None):
    assets, destination = Path(assets).resolve(), Path(destination).resolve()
    share = Path(share or ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco')
    manifest = json.loads((assets/'manifest.json').read_text())
    if manifest.get('license') != 'MIT' or any(sha(assets/f['file']) != f['sha256'] for f in manifest['files']):
        raise ValueError('Cached object assets do not match their provenance')
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    shutil.copyfile(share/'mjcf/fishbot_inspection.xml', destination/'fishbot_inspection.xml')
    scene = ET.parse(share/'mjcf/inspection.xml')
    scene.getroot().set('model', 'fishbot_pretrained_object_inspection')
    world, asset = scene.find('worldbody'), scene.find('asset')
    for geom in list(world.findall('geom')):
        if geom.get('name', '').startswith('station_'):
            world.remove(geom)
    for name in ASSETS:
        shutil.copyfile(assets/name, destination/name)
        scale = '1.8 1.8 1.8' if name in ('mug.stl','handle.stl') else '1 1 1'
        ET.SubElement(asset, 'mesh', name='object_'+Path(name).stem, file=name, scale=scale)
    # Original MetaWorld object materials and mesh assembly, scaled to everyday size.
    for name, rgba in [('mug','0.85 0.85 0.85 1'),('laptop_black','0.15 0.15 0.15 1'),
                       ('laptop_grey','0.3 0.3 0.35 1')]:
        ET.SubElement(asset, 'material', name='object_'+name, rgba=rgba, specular='.5', shininess='1')
    for index, x in enumerate((.5,1.5,2.5,3.3)):
        # The low onboard camera needs to see the laptop keyboard, not only its screen.
        top = .10 if index == 1 else .20
        ET.SubElement(world, 'geom', name=f'object_support_{index}', type='box',
            pos=f'{x} 1.15 {top/2}', size=f'.16 .16 {top/2}', rgba='.5 .45 .4 1')
    for name, x in [('cup_visible',.5),('cup_occluded',2.5)]:
        body = ET.SubElement(world, 'body', name=name, pos=f'{x} 1.15 .20')
        ET.SubElement(body, 'geom', type='mesh', mesh='object_mug', pos='0 0 .0612',
                      material='object_mug', contype='0', conaffinity='0')
        ET.SubElement(body, 'geom', type='mesh', mesh='object_handle', pos='.0702 0 .0846',
                      euler='1.571 0 0', material='object_mug', contype='0', conaffinity='0')
    laptop = ET.SubElement(world, 'body', name='laptop_visible', pos='1.5 1.15 .10')
    for part in ('base','keys'):
        ET.SubElement(laptop,'geom',type='mesh',mesh='object_laptop_'+part,pos='0 0 .015',
                      material='object_laptop_grey',contype='0',conaffinity='0')
    lid = ET.SubElement(laptop,'body',pos='0 .151 .031')
    for part,material in [('screen','laptop_black'),('top','laptop_grey')]:
        ET.SubElement(lid,'geom',type='mesh',mesh='object_laptop_'+part,pos='0 .01 .15',
                      material='object_'+material,contype='0',conaffinity='0')
    ET.SubElement(lid,'geom',type='mesh',mesh='object_laptop_hinge',euler='0 1.57 0',
                  material='object_laptop_grey',contype='0',conaffinity='0')
    ET.SubElement(world, 'geom', name='object_occluder', type='box', pos='2.5 .93 .28',
                  size='.20 .02 .14', rgba='.5 .52 .54 1')
    scene.write(destination/'scene.xml', encoding='utf-8', xml_declaration=True)
    route = dict(home=[0.,0.,0.], stations=[
        dict(name='cup', question='Is a cup observed?', label='cup', goal=[.5,.45,math.pi/2]),
        dict(name='laptop', question='Is a laptop observed?', label='laptop', goal=[1.5,.45,math.pi/2]),
        dict(name='occluded-cup', question='Is a cup observed?', label='cup', goal=[2.5,.45,math.pi/2],
             alternate_goal=[2.5,1.85,-math.pi/2]),
        dict(name='absent-cup', question='Is a cup observed?', label='cup', goal=[3.3,.45,math.pi/2],
             alternate_goal=[3.1,.55,math.atan2(.6,.2)]),
    ])
    (destination/'route.json').write_text(json.dumps(route, indent=2)+'\n')
    provenance = dict(schema_version=1, scene_sha256=sha(destination/'scene.xml'),
        route_sha256=sha(destination/'route.json'),
        robot_source_sha256=sha(share/'mjcf/fishbot_inspection.xml'), assets=manifest,
        fixture_selection={'model':'YOLO11n COCO', 'selection_scope':'Hand-selected synthetic recognition fixture; not a detector accuracy benchmark',
            'rejected_candidates':[{'asset':'MetaWorld basketball','prediction':'orange'},
                                   {'asset':'MetaWorld soccer','prediction':'umbrella'},
                                   {'asset':'MetaWorld laptop on 20 cm support','prediction':'tv'}],
            'selected_candidates':['MetaWorld cup','MetaWorld laptop on 10 cm support'],
            'camera':'Original onboard camera unchanged; lower support reveals laptop keyboard',
            'alternate_view_selection':{'rejected_left':'Runtime arrival hid cup handle; unknown preserved',
                'rejected_front_right':'Only 18/27 hand-selected pose perturbations detected cup',
                'selected_rear':[2.5,1.85,-math.pi/2],
                'static_pose_variants':27,'static_cup_detections':27,
                'confidence_range':[.619,.947],
                'scope':'Fixture view selection only; not detector accuracy or runtime acceptance'}},
        scope='Public synthetic fixture; detection consumes RGB only; truth binds capture pose only.')
    (destination/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
    shutil.copyfile(assets/'LICENSE-MetaWorld', destination/'LICENSE-MetaWorld')
    return destination/'scene.xml'


def prepare_navigation(share, output):
    """Copy the baseline; change only the already measured AMCL likelihood profile."""
    import yaml
    share,output=Path(share),Path(output)
    source=share/'config/nav2.yaml'
    params=yaml.safe_load(source.read_text())
    params['amcl']['ros__parameters'].update(AMCL_PROFILE)
    progress_source=ROOT/'tools/config/fishbot_passage_nav.yaml'
    measured=yaml.safe_load(progress_source.read_text())
    progress=measured['controller_server']['ros__parameters']['progress_checker']
    params['controller_server']['ros__parameters']['progress_checker']=progress.copy()
    destination=output/'nav2.yaml'
    with destination.open('x') as file:yaml.safe_dump(params,file,sort_keys=False)
    provenance=json.loads((output/'provenance.json').read_text())
    provenance['navigation_profile']={'source_sha256':sha(source),'generated_sha256':sha(destination),
        'amcl_overrides':AMCL_PROFILE,'progress_checker_source_sha256':sha(progress_source),
        'progress_checker_override':progress,
        'scope':'Fixture-only measured AMCL and pose-progress profile; baseline, collision/RPP and observation tolerance unchanged'}
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return destination


def render_views(scene, output):
    """Static camera preview only. No ROS, physics navigation, or recognition truth."""
    import mujoco
    from PIL import Image
    scene, output = Path(scene), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    address = model.jnt_qposadr[mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,'base_free_joint')]
    route = json.loads((scene.parent/'route.json').read_text())
    with mujoco.Renderer(model, height=480, width=640) as renderer:
        for station in route['stations']:
            views = [('primary', station['goal'])]
            if 'alternate_goal' in station:
                views.append(('alternate',station['alternate_goal']))
            for view, (x,y,yaw) in views:
                mujoco.mj_resetData(model,data)
                data.qpos[address:address+2] = (x,y)
                data.qpos[address+3:address+7] = (math.cos(yaw/2),0,0,math.sin(yaw/2))
                mujoco.mj_forward(model,data)
                renderer.update_scene(data,camera='inspection_camera')
                Image.fromarray(renderer.render()).save(output/f'{station["name"]}-{view}.png')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='mode',required=True)
    prep=sub.add_parser('assets');prep.add_argument('--source',type=Path,required=True)
    prep.add_argument('--license',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    build=sub.add_parser('build');build.add_argument('--assets',type=Path,required=True)
    build.add_argument('--output',type=Path,required=True)
    render=sub.add_parser('render');render.add_argument('--scene',type=Path,required=True)
    render.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.mode=='assets':prepare_assets(a.source,a.license,a.output)
    elif a.mode=='build':print(build_scene(a.assets,a.output))
    else:render_views(a.scene,a.output)


if __name__=='__main__':main()
