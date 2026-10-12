#!/usr/bin/env python3
"""Actual YOLO11n COCO inference. Inputs are RGB images, never scene metadata."""
import argparse
import contextlib
import hashlib
import json
import math
from pathlib import Path
import sys
import time

MODEL_SHA256='0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1'


def validate_weight(model):
    model=Path(model).resolve()
    if not model.is_file() or model.suffix!='.pt':
        raise ValueError('Supply an existing official .pt weight; automatic downloads are disabled')
    weight_sha=hashlib.sha256(model.read_bytes()).hexdigest()
    if weight_sha!=MODEL_SHA256:
        raise ValueError('Weight does not match the pinned official YOLO11n COCO artifact')
    return model,weight_sha


class Detector:
    def __init__(self, model, confidence=.35, device='cpu'):
        model,weight_sha=validate_weight(model)
        import torch
        import ultralytics
        from ultralytics import YOLO
        if not math.isfinite(confidence) or not 0<confidence<1:
            raise ValueError('Invalid detector confidence')
        torch.set_num_threads(2)
        self.model=YOLO(str(model));self.confidence=confidence;self.device=device
        self.metadata=dict(family='YOLO11n COCO',license='AGPL-3.0',ultralytics=ultralytics.__version__,
            torch=torch.__version__,device=device,weight_sha256=weight_sha,
            source='https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt')

    def predict(self, rgb):
        import numpy as np
        if not isinstance(rgb,np.ndarray) or rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:
            raise ValueError('Expected RGB uint8 image')
        if not 1<=rgb.shape[0]<=4096 or not 1<=rgb.shape[1]<=4096:
            raise ValueError('Invalid RGB dimensions')
        started=time.monotonic()
        # Ultralytics' ndarray API explicitly consumes BGR, unlike PIL inputs.
        result=self.model.predict(rgb[:,:,::-1].copy(),imgsz=640,conf=self.confidence,
                                  device=self.device,verbose=False)[0]
        detections=[]
        for box in result.boxes:
            confidence=float(box.conf.item());coordinates=[float(v) for v in box.xyxy[0].tolist()]
            if not all(math.isfinite(v) for v in [confidence,*coordinates]):
                raise RuntimeError('Model produced nonfinite detection')
            if not (0<=coordinates[0]<coordinates[2]<=rgb.shape[1] and
                    0<=coordinates[1]<coordinates[3]<=rgb.shape[0]):
                raise RuntimeError('Model box lies outside input image')
            class_id=int(box.cls.item())
            detections.append(dict(label=self.model.names[class_id],class_id=class_id,
                                   confidence=confidence,xyxy=coordinates))
        return dict(model=self.metadata,wall_ms=(time.monotonic()-started)*1000,
                    detections=detections,width=rgb.shape[1],height=rgb.shape[0])


def main():
    from PIL import Image
    import numpy as np
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--confidence',type=float,default=.35);p.add_argument('--device',default='cpu')
    p.add_argument('--worker',action='store_true');p.add_argument('--images',type=Path,nargs='+')
    p.add_argument('--output',type=Path);a=p.parse_args()
    # Keep the worker stdout protocol clean when a first-run library creates settings.
    with contextlib.redirect_stdout(sys.stderr):
        detector=Detector(a.model,a.confidence,a.device)
        if a.worker:detector.predict(np.zeros((480,640,3),dtype=np.uint8))
    if a.worker:
        print(json.dumps({'ready':True,'model':detector.metadata}),flush=True)
        for line in sys.stdin:
            try:
                request=json.loads(line)
                rgb=np.asarray(Image.open(request['image']).convert('RGB'))
                with contextlib.redirect_stdout(sys.stderr):result=detector.predict(rgb)
                result['input_sha256']=hashlib.sha256(Path(request['image']).read_bytes()).hexdigest()
                print(json.dumps(result,allow_nan=False),flush=True)
            except Exception as exc:
                print(json.dumps({'error':f'{type(exc).__name__}: {exc}'}),flush=True)
                return 1
        return 0
    if not a.images or a.output is None:p.error('Supply --images and --output, or --worker')
    frames=[]
    for image in a.images:
        result=detector.predict(np.asarray(Image.open(image).convert('RGB')))
        frames.append(dict(image=str(image.resolve()),sha256=hashlib.sha256(image.read_bytes()).hexdigest(),**result))
    with a.output.open('x') as f:json.dump(dict(model=detector.metadata,frames=frames),f,indent=2,allow_nan=False)
    print(json.dumps({'frames':len(frames),'output':str(a.output)}))
    return 0


if __name__=='__main__':raise SystemExit(main())
