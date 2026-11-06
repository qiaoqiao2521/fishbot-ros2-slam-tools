#!/usr/bin/env python3
"""Reuse the verified visual GPU bootstrap for two independently scored scenes."""
import importlib.util
import os
from pathlib import Path
import tarfile

os.environ['FISHBOT_CLOSURE_SCENES'] = 'f2-wide-warehouse,f2-workshop-line'
sources = list(Path('/kaggle/input').rglob('f1-visual-source.tar.gz.bin'))
if len(sources) != 1:
    raise RuntimeError('Attach one explicitly selected existing source dataset')
root = Path('/tmp/fishbot-closure-entry'); root.mkdir(exist_ok=False)
with tarfile.open(sources[0], 'r:gz') as archive:
    for name in ['fishbot/experiments/kaggle/f1_gl_audit.py']:
        archive.extract(name, root, filter='data')
source = root/'fishbot/experiments/kaggle/f1_gl_audit.py'
spec = importlib.util.spec_from_file_location('closure_gpu_bootstrap', source)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.main()
