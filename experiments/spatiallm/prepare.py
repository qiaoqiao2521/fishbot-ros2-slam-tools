"""Provision pinned public sources and the official GT sample outside Git."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

SOURCE_URL = "https://github.com/manycore-research/SpatialLM.git"
SOURCE_COMMIT = "8913c44d84a450c53e9340b13317f8cf7144a738"
DATASET_REVISION = "60bab76febb0c9635f58e156f32e906afc91a499"
SAMPLE_FILES = {
    "layout/scene0000_00.txt": (2085, "2f3314cee1c864061b20459793a91aafa49bce111325a199f5dbe0340b918893"),
    "pcd/scene0000_00.ply": (10968451, "12d8cf9c239791260166837d090334915f7056537a2e35c97959d9842a6c5f92"),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch_sample(cache: Path):
    sample = cache / "sample"
    records = {}
    for name, (size, expected) in SAMPLE_FILES.items():
        path = sample / name
        url = f"https://huggingface.co/datasets/manycore-research/SpatialLM-Testset/resolve/{DATASET_REVISION}/{name}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.stat().st_size != size or digest(path) != expected:
                raise ValueError(f"existing {path} differs from the pinned sample; choose a new cache")
        else:
            temporary = path.with_suffix(path.suffix + ".download")
            if temporary.exists():
                raise ValueError(f"incomplete download remains at {temporary}; inspect it before retrying")
            count = 0
            try:
                with urllib.request.urlopen(url, timeout=60) as response, temporary.open("xb") as output:
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        if count > size:
                            raise ValueError(f"download exceeds the expected size for {name}")
                        output.write(chunk)
                if count != size or digest(temporary) != expected:
                    raise ValueError(f"size/SHA256 verification failed for {name}")
                temporary.rename(path)
            except Exception:
                # Retain incomplete bytes for diagnosis; never report them as a sample.
                raise
        records[name] = {"url": url, "revision": DATASET_REVISION, "bytes": size, "sha256": expected}
    manifest = {"kind": "official_testset_ground_truth", "dataset_revision": DATASET_REVISION,
                "license": "CC-BY-NC-4.0", "attribution": "Manycore Research SpatialLM-Testset",
                "license_url": "https://huggingface.co/datasets/manycore-research/SpatialLM-Testset",
                "sample_id": "scene0000_00", "files": records,
                "limits": "GT annotation, not a model prediction produced by this software."}
    (sample / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return sample


def provision(cache: Path):
    cache = cache.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    source = cache / "source" / "SpatialLM"
    if not source.exists():
        source.parent.mkdir(exist_ok=True)
        subprocess.run(["git", "clone", "--no-checkout", SOURCE_URL, str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", SOURCE_COMMIT], check=True)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != SOURCE_COMMIT:
        raise ValueError("existing source has a different revision; it will not be reset")
    # Reuse the production importer to verify the actual modules, not just git HEAD.
    from scene_import import load_layout
    sample = fetch_sample(cache)
    doc = load_layout((sample / "layout/scene0000_00.txt").read_text(), source,
                      {"kind": "official_testset_ground_truth", "dataset_revision": DATASET_REVISION})
    (cache / "prepared.json").write_text(json.dumps({"source_dir": str(source), "source_commit": SOURCE_COMMIT,
                 "sample_layout": str(sample / "layout/scene0000_00.txt"),
                 "sample_point_cloud": str(sample / "pcd/scene0000_00.ply"),
                 "layout_source": doc["source"]}, indent=2) + "\n")
    return source, sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path.home() / ".cache/fishbot-spatiallm/prepared")
    args = parser.parse_args()
    source, sample = provision(args.cache_dir)
    print(json.dumps({"source_dir": str(source), "sample_layout": str(sample / "layout/scene0000_00.txt"),
                      "sample_point_cloud": str(sample / "pcd/scene0000_00.ply")}, indent=2))


if __name__ == "__main__":
    main()
