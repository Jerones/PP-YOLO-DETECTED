# -*- coding: utf-8 -*-
"""表计读数推理流水线。

图片检测（detect）与摄像头检测（detect_image）共用同一条流水线，
避免两处实现各自演化导致结果不一致。

线程安全：同一次流水线会连续使用两块模型，若图片检测与摄像头检测同时进来
会互相抢占 CPU 线程池，实测帧率反而下降。这里用一把全局锁把推理串行化。
"""

import threading

import cv2
import numpy as np

from paths import resource_path
# 显式列出用到的算子，而不是 from util import *：一眼能看出本模块依赖
# 流水线的哪几步，也避免 math / cv2 之类被带进来污染命名空间
from util import (METER_CONFIG, TYPE_THRESHOLD, Model, calculate_reading,
                  circle_to_rectangle, det_preprocess, erode, filter_bboxes,
                  get_relative_location, locate_pointer, locate_scale,
                  mean_binarization, rectangle_to_line, roi_crop, roi_process)

DET_MODEL_PATH = resource_path("model/meter_det_model/model.pdmodel")
DET_MODEL_SHAPE = {'image': [1, 3, 608, 608], 'im_shape': [1, 2], 'scale_factor': [1, 2]}
SEG_MODEL_PATH = resource_path("model/meter_seg_model/model.pdmodel")
SEG_MODEL_SHAPE = {'image': [1, 3, 512, 512]}

ERODE_KERNEL = 4
SCORE_THRESHOLD = 0.5
INPUT_SHAPE = 608

# 模型延迟加载并缓存为进程级单例：图片检测与视频检测共用同一份编译结果，
# 避免重复加载导致内存翻倍；延迟到首次调用也便于在启动阶段捕获路径/依赖错误。
_models = None
_model_lock = threading.Lock()
_infer_lock = threading.Lock()


def _load_models():
    global _models
    if _models is None:
        with _model_lock:
            if _models is None:
                _models = (Model(DET_MODEL_PATH, DET_MODEL_SHAPE),
                           Model(SEG_MODEL_PATH, SEG_MODEL_SHAPE))
    return _models


def warmup():
    """预加载模型，让路径或依赖问题在启动阶段暴露出来。"""
    _load_models()


def is_wide(frame):
    """判断画面是否为 16:9。

    检测框反算依赖实测标定的横向系数（见 detect_image 注释），该系数只在
    16:9 输入下成立。非 16:9 时框会横向失真，需要先转成 16:9 再推理。
    """
    height, width = frame.shape[0:2]
    if height <= 0:
        return True
    return abs(width / height - 16.0 / 9.0) < 0.05


def to_wide(frame):
    """把任意画面等比缩放并居中填充到 16:9，返回 (画布, 变换参数)。

    直接 resize 会让表盘由圆变椭圆，而分割模型对圆形表盘训练，
    因此必须等比缩放后补边，再把结果坐标反算回原图。
    """
    height, width = frame.shape[0:2]
    if is_wide(frame):
        return frame, None
    target_w = width
    target_h = int(round(width * 9.0 / 16.0))
    if target_h < height:
        # 画面偏方：按高度定宽，两侧补边
        target_h = height
        target_w = int(round(height * 16.0 / 9.0))
    scale = min(target_w / float(width), target_h / float(height))
    new_w, new_h = int(round(width * scale)), int(round(height * scale))
    canvas = np.zeros((target_h, target_w, 3), dtype=frame.dtype)
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    x0 = (target_w - new_w) // 2
    y0 = (target_h - new_h) // 2
    canvas[y0:y0 + new_h, x0:x0 + new_w] = resized
    return canvas, {'scale': scale, 'x0': x0, 'y0': y0}


def _to_original(box, transform):
    """把 16:9 画布坐标下的框反算回原始画面坐标。"""
    if transform is None or not box:
        return box
    inv = 1.0 / transform['scale']
    return [int((box[0] - transform['x0']) * inv),
            int((box[1] - transform['y0']) * inv),
            int((box[2] - transform['x0']) * inv),
            int((box[3] - transform['y0']) * inv)]


def detect_image(image):
    """对一张 BGR 图像执行完整读数流程。

    参数：
        image (np.ndarray)：BGR 图像
    返回：
        (result_image, readings, meters)
        - result_image：标注了检测框与读数的副本，未检出时返回原图副本
        - readings：每块表的读数（float 列表，保持与旧接口一致）
        - meters：每块表的详细信息列表，字段见下方 build
    """
    detector, segmenter = _load_models()

    # 非 16:9 画面先补成 16:9，保证检测框反算系数成立
    work, transform = to_wide(image)

    with _infer_lock:
        im_shape = np.array([[INPUT_SHAPE, INPUT_SHAPE]]).astype('float32')
        scale_factor = np.array([[1, 2]]).astype('float32')
        input_image = det_preprocess(work, INPUT_SHAPE)
        det_results = detector.predict({'image': input_image,
                                        'im_shape': im_shape,
                                        'scale_factor': scale_factor})
        filtered_results = filter_bboxes(det_results, SCORE_THRESHOLD)
        if len(filtered_results) == 0:
            return image.copy(), [], []

        # 把检测框从 608 输入空间反算回工作画面坐标。
        # 横向的 *2 是实测标定值：对 1920x1080 / 1280x720 / 640x360 归一化后
        # 框位置完全一致，说明它等价于「按画面宽高比补偿模型的横向压缩」，
        # 因此只在 16:9 成立。to_wide 已保证进入这里的是 16:9 画面。
        scale_x = work.shape[1] / INPUT_SHAPE * 2
        scale_y = work.shape[0] / INPUT_SHAPE
        roi_imgs, loc = roi_crop(work, filtered_results, scale_x, scale_y)

        boxes = [[int(v) for v in box] for box in loc]
        roi_imgs, _ = roi_process(roi_imgs, (512, 512))
        seg_results = [segmenter.predict({'image': np.array([img])})[0]
                       for img in roi_imgs]

    seg_results = [np.argmax(res, axis=0) for res in seg_results]
    seg_results = erode(seg_results, ERODE_KERNEL)

    rectangle_meters = circle_to_rectangle(seg_results)
    line_scales, line_pointers = rectangle_to_line(rectangle_meters)
    binaried_scales = mean_binarization(line_scales)
    binaried_pointers = mean_binarization(line_pointers)
    scale_locations = locate_scale(binaried_scales)
    pointer_locations = locate_pointer(binaried_pointers)
    pointed_scales = get_relative_location(scale_locations, pointer_locations)
    readings = calculate_reading(pointed_scales)

    meters = []
    for index, reading in enumerate(readings):
        info = pointed_scales[index]
        num_scales = info['num_scales']
        config = METER_CONFIG[0] if num_scales > TYPE_THRESHOLD else METER_CONFIG[1]
        # pointed_scale 为 -1 表示指针没落在任何相邻刻度区间内，
        # 此时 calculate_reading 给出负值，属无效读数，不能参与告警与记录
        valid = (num_scales > 0 and info['pointed_scale'] > 0 and reading > 0)
        meters.append({
            'index': index + 1,
            'reading': float(reading),
            'num_scales': num_scales,
            'range': float(config['range']),
            'unit': config['unit'].strip('()'),
            'valid': bool(valid),
            'box': _to_original(boxes[index], transform) if index < len(boxes) else None,
        })

    result_image = image.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    for meter in meters:
        box = meter.get('box')
        if not box:
            continue
        x1, y1, x2, y2 = box
        color = (0, 150, 0) if meter['valid'] else (0, 110, 200)
        label = "#{:.3f}".format(meter['reading']) if meter['valid'] else "#--"
        cv2.rectangle(result_image, (x1, y1), (x2, y2), color, 3)
        cv2.rectangle(result_image, (x1, y1), (x1 + 130, y1 + 40), color, -1)
        cv2.putText(result_image, label, (x1 + 6, y1 + 28),
                    font, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

    return result_image, readings, meters


def detect(img_file):
    """读取图片文件并检测。

    参数：
        img_file (str)：图片路径，支持中文路径
    返回：
        (result_image, readings, meters)：同 detect_image
    """
    # 用 imdecode 而非 imread，规避 OpenCV 在中文路径下读取失败的问题
    image = cv2.imdecode(np.fromfile(img_file, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(
            '无法读取图片，文件可能已损坏或不是有效图片格式：{}'.format(img_file))
    return detect_image(image)


if __name__ == '__main__':
    _img, _nums, _meters = detect("data/meter_test/20190822_105.jpg")
    print(_nums)
    print(_meters)
    cv2.imshow('result', _img)
    cv2.waitKey()
