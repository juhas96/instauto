import json
from pathlib import Path
from typing import Union, List
import os
import platform
import datetime


def get_image_type(p: Union[str, Path]) -> str:
    """Returns the type of image, i.e. jpeg or png."""
    if isinstance(p, Path):
        return p.suffix
    return p.split('.')[-1]


def build_default_rupload_params(upload_id: str, quality: int) -> dict:
    """Builds default parameters used to upload media."""
    return {
        'upload_id': upload_id,
        'media_type': 1,
        'retry_context': json.dumps({
            'num_reupload': 0,
            'num_step_auto_retry': 0,
            'num_step_manual_retry': 0,
        }),
        'xsharing_user_ids': json.dumps([]),
        'image_compression': json.dumps({
            'lib_name': 'moz',
            'lib_version': '3.1.m',
            'quality': str(quality)
        })
    }


def get_creation_date(path: str) -> str:
    if platform.system() == 'Windows':
        timestamp = os.path.getctime(path)
    else:
        stat = os.stat(path)
        try:
            timestamp = stat.st_birthtime
        except AttributeError:
            timestamp = stat.st_mtime
    dt = datetime.datetime.fromtimestamp(timestamp)
    return f"{dt.year}{dt.month}{dt.day}T{dt.hour}{dt.minute}{dt.second}.000Z"


def remove_from_dict(input_dict: dict, to_remove: List[str]) -> dict:
    for k in to_remove:
        try:
            input_dict.pop(k)
        except AttributeError:
            continue
    return input_dict
