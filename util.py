import numpy as np
import cv2
import openvino.runtime as ov

# 表盘几何常量。分割标签图固定 512x512，圆心与半径是据此标定的，
# 改动这里等于改动读数换算的全部依据，不要随手调。
CIRCLE_CENTER = [256, 256]
CIRCLE_RADIUS = 250
PI = 3.1415926536
RECTANGLE_HEIGHT = 120
RECTANGLE_WIDTH = 1570
TYPE_THRESHOLD = 40

# There are 2 types of meter in test image data-sets
METER_CONFIG = [{
    'scale_interval_value': 25.0 / 50.0,
    'range': 25.0,
    'unit': "(MPa)"
}, {
    'scale_interval_value': 1.6 / 32.0,
    'range': 1.6,
    'unit': "(MPa)"
}]


SEG_LABEL = {'background': 0, 'pointer': 1, 'scale': 2}

###该函数用于对输入图像进行预处理，以便用于检测任务。预处理包括将输入图像调整为模型所需的指定尺寸，并进行必要的数据类型转换和归一化操作，以确保模型能够正确处理图像数据。
def det_preprocess(input_image, target_size):
    """
    为检测任务预处理输入数据

    参数： 
        input_image (np.array)：输入数据
        size (int)：模型输入层所需的图像尺寸
    返回：
        img.astype(np.array)：预处理后的图像

    
    """
    img = cv2.resize(input_image, (target_size, target_size))
    img = np.transpose(img, [2, 0, 1]) / 255
    img = np.expand_dims(img, 0)
    img_mean = np.array([0.485, 0.456, 0.406]).reshape((3, 1, 1))
    img_std = np.array([0.229, 0.224, 0.225]).reshape((3, 1, 1))
    img -= img_mean
    img /= img_std
    return img.astype(np.float32)

###要过滤掉低置信度的检测结果，可以通过比较每个检测结果的置信度分数（score）与预设的阈值来实现。只有当置信度分数高于阈值时，才将该检测结果保留，否则将其丢弃。
def filter_bboxes(det_results, score_threshold):
    """
    过滤掉低置信度的检测结果
    参数：
        det_results (list[dict])：检测结果
        score_threshold (float)：置信度阈值
    返回：
        filtered_results (list[dict])：过滤后的检测结果 
    """
    filtered_results = []
    for i in range(len(det_results)):
        if det_results[i, 1] > score_threshold:
            filtered_results.append(det_results[i])
    return filtered_results

###要从原始图像中裁剪检测到的仪表区域，您将使用检测结果来识别和提取感兴趣区域 （ROI）。这涉及根据检测到的边界框和提供的缩放因子处理原始图像。

def roi_crop(image, results, scale_x, scale_y):
    """
    裁剪原始图像中检测到的仪表区域
    参数：
        img (np.array)：原始图像。
        det_results (list[dict])：检测结果
        scale_x (float)：x轴上的比例尺值
        scale_y (float)：y轴上的比例尺值
    返回：
        roi_imgs (list[np.array])：裁剪后的仪表图像列表
        loc (list[int])：仪表位置列表
    """
    roi_imgs = []
    loc = []
    for result in results:
        bbox = result[2:]
        xmin, ymin, xmax, ymax = [int(bbox[0] * scale_x), int(bbox[1] * scale_y), int(bbox[2] * scale_x), int(bbox[3] * scale_y)]
        sub_img = image[ymin:(ymax + 1), xmin:(xmax + 1), :]
        roi_imgs.append(sub_img)
        loc.append([xmin, ymin, xmax, ymax])
    return roi_imgs, loc

###在进行图像分割任务之前，需要对输入的表具图像进行预处理，包括调整大小和插值处理，以确保适合于分割模型的输入要求。
def roi_process(input_images, target_size, interp=cv2.INTER_LINEAR):
    """
    准备检测结果数据的感兴趣区域图像
    对分割任务的输入数据进行预处理

    参数：
        input_images (list[np.array])：表具图像的列表
        target_size (list|tuple)：调整后的图像高度和宽度，例如 [高度,宽度]
        interp (int)：图像调整的插值方法
    返回：
        img_list (list[np.array])：处理后的图像列表
        resize_img (list[np.array]): 用于可视化的调整图像  
    """
    img_list = list()
    resize_list = list()
    for img in input_images:
        img_shape = img.shape
        scale_x = float(target_size[1]) / float(img_shape[1])
        scale_y = float(target_size[0]) / float(img_shape[0])
        resize_img = cv2.resize(img, None, None, fx=scale_x, fy=scale_y, interpolation=interp)
        resize_list.append(resize_img)
        resize_img = resize_img.transpose(2, 0, 1) / 255
        img_mean = np.array([0.5, 0.5, 0.5]).reshape((3, 1, 1))
        img_std = np.array([0.5, 0.5, 0.5]).reshape((3, 1, 1))
        resize_img -= img_mean
        resize_img /= img_std
        img_list.append(resize_img)
    return img_list, resize_list

###腐蚀操作在图像处理中用于减少或移除图像中物体边界处的像素。在本情况下，对分割结果进行腐蚀可以使指针和刻度的边界更加清晰，有助于进一步的分析和测量。
def erode(seg_results, erode_kernel):
    """
    对分割结果进行腐蚀处理，以获取更清晰的指针和刻度实例

    参数：
        seg_results (list[dict])：分割结果
        erode_kernel (int): 腐蚀核的大小

    返回：
        eroded_results (list[dict])：腐蚀后的标签映射图

        
    """
    kernel = np.ones((erode_kernel, erode_kernel), np.uint8)
    # 返回新列表，不就地覆盖入参，避免调用方持有的分割结果被悄悄改写
    return [cv2.erode(seg_result.astype(np.uint8), kernel) for seg_result in seg_results]

###这个函数的目的是将从分割模型得到的圆形标签地图转换为矩形形状，以便进一步处理和分析目标区域的数据。
def circle_to_rectangle(seg_results):
    """
        将标签地图的形状从圆形切换为矩形
    参数：
        seg_results (list[dict])：分割结果
    返回：
        rectangle_meters (list[np.array])：矩形标签地图
    """
    if not seg_results:
        return []

    # 采样坐标只与几何参数有关、与图像内容无关，一次算好供所有表复用。
    # 向量化后把原来的 120×1570 次 Python 循环压成一次数组索引，单表耗时从百毫秒级降到毫秒级。
    theta = PI * 2 * (np.arange(RECTANGLE_WIDTH) + 1) / RECTANGLE_WIDTH
    rho = (CIRCLE_RADIUS - np.arange(RECTANGLE_HEIGHT) - 1).reshape(-1, 1)

    # 半径由小到大映射到矩形自上而下，角度映射到矩形自左向右
    ys = (CIRCLE_CENTER[0] + rho * np.cos(theta) + 0.5).astype(np.int32)
    xs = (CIRCLE_CENTER[1] - rho * np.sin(theta) + 0.5).astype(np.int32)

    rectangle_meters = list()
    for label_map in seg_results:
        height, width = label_map.shape[0:2]
        rectangle_meters.append(label_map[np.clip(ys, 0, height - 1),
                                          np.clip(xs, 0, width - 1)].astype(np.uint8))
    return rectangle_meters

###在处理2D矩形标签地图时，通常需要将其转换为1D形式以便进一步处理。这种转换可以通过将矩形地图的每行或每列展平成一个单一的数组来实现。比例尺值和指针值分别表示为转换后的1D数组，便于后续分析和处理
def rectangle_to_line(rectangle_meters):
    """
    将矩形标签地图的维度从2D转换为1D

    参数：
        rectangle_meters (list[np.array])：2D矩形标签地图

    返回：
        line_scales (list[np.array])：比例尺值的列表
        line_pointers (list[np.array])：指针值的列表

    """
    line_scales = list()
    line_pointers = list()
    for rectangle_meter in rectangle_meters:
        # 按列统计各类标签的像素数，等价于原来的双重循环，但走 C 层实现
        line_pointer = np.count_nonzero(rectangle_meter == SEG_LABEL['pointer'],
                                        axis=0).astype(np.uint8)
        line_scale = np.count_nonzero(rectangle_meter == SEG_LABEL['scale'],
                                      axis=0).astype(np.uint8)
        line_scales.append(line_scale)
        line_pointers.append(line_pointer)
    return line_scales, line_pointers

###数据二值化是将输入数据转换为二进制形式的过程。通常用于将连续型数据转换为二值数据，便于后续处理或分析。
def mean_binarization(data_list):
    """
    数据二值化

    参数：
        data_list (list[np.array])：输入数据

    返回：
        binaried_data_list (list[np.array])：输出数据


    """
    binaried_data_list = list()
    for data in data_list:
        # 等价于逐列比较：小于均值置 0，否则置 1；向量化后不再就地改写入参
        binaried_data_list.append((data >= np.mean(data)).astype(np.uint8))
    return binaried_data_list

###这个函数用于从二值化的刻度值列表中找到每个刻度的中心位置。
def locate_scale(line_scales):
    """
    寻找每个刻度的中心位置

    参数：
        line_scales (list[np.array])：二值化刻度值的列表

    返回：
        scale_locations (list[list])：每个刻度的位置列表


    """
    batch_size = len(line_scales)
    scale_locations = list()
    for i in range(batch_size):
        line_scale = line_scales[i]
        width = line_scale.shape[0]
        find_start = False
        one_scale_start = 0
        one_scale_end = 0
        locations = list()
        for j in range(width - 1):
            if line_scale[j] > 0 and line_scale[j + 1] > 0:
                if not find_start:
                    one_scale_start = j
                    find_start = True
            if find_start:
                if line_scale[j] == 0 and line_scale[j + 1] == 0:
                    one_scale_end = j - 1
                    one_scale_location = (one_scale_start + one_scale_end) / 2
                    locations.append(one_scale_location)
                    one_scale_start = 0
                    one_scale_end = 0
                    find_start = False
        scale_locations.append(locations)
    return scale_locations

###该函数用于从二值化的指针数值列表中找到指针中心的位置。这些位置以二维列表的形式返回。
def locate_pointer(line_pointers):
    """
    找到指针中心的位置
    
    参数：
        line_scales (list[np.array])：二值化指针数值的列表

    返回：
        scale_locations (list[list])：指针位置的列表


    """
    batch_size = len(line_pointers)
    pointer_locations = list()
    for i in range(batch_size):
        line_pointer = line_pointers[i]
        find_start = False
        pointer_start = 0
        pointer_end = 0
        location = 0
        width = line_pointer.shape[0]
        for j in range(width - 1):
            if line_pointer[j] > 0 and line_pointer[j + 1] > 0:
                if not find_start:
                    pointer_start = j
                    find_start = True
            if find_start:
                if line_pointer[j] == 0 and line_pointer[j + 1] == 0 :
                    pointer_end = j - 1
                    location = (pointer_start + pointer_end) / 2
                    find_start = False
                    break
        pointer_locations.append(location)
    return pointer_locations


def get_relative_location(scale_locations, pointer_locations):
    """
    匹配指针和刻度的位置
    
    参数：
        scale_locations (list[list])：每个刻度的位置
        pointer_locations (list[list])：指针的位置

    返回：
        pointed_scales (list[dict])：一个包含以下字典的列表：
                                 'num_scales'：刻度总数
                                 'pointed_scale'：预测的刻度数量

            
    """
    pointed_scales = list()
    for scale_location, pointer_location in zip(scale_locations,
                                                pointer_locations):
        num_scales = len(scale_location)
        pointed_scale = -1
        if num_scales > 0:
            for i in range(num_scales - 1):
                if scale_location[i] <= pointer_location < scale_location[i + 1]:
                    pointed_scale = i + (pointer_location - scale_location[i]) / (scale_location[i + 1] - scale_location[i] + 1e-05) + 1
        result = {'num_scales': num_scales, 'pointed_scale': pointed_scale}
        pointed_scales.append(result)
    return pointed_scales


def calculate_reading(pointed_scales):
    """
    根据仪表类型计算仪表的值
    
    参数：
        pointed_scales (list[list])：预测的刻度数量

    返回：
        readings (list[float])：从仪表读取的值列表

            
    """
    readings = list()
    batch_size = len(pointed_scales)
    for i in range(batch_size):
        pointed_scale = pointed_scales[i]
        # find the type of meter according the total number of scales
        if pointed_scale['num_scales'] > TYPE_THRESHOLD:
            reading = pointed_scale['pointed_scale'] * METER_CONFIG[0]['scale_interval_value']
        else:
            reading = pointed_scale['pointed_scale'] * METER_CONFIG[1]['scale_interval_value']
        readings.append(reading)
    return readings



# Initialize inference engine
ie_core = ov.Core()

class Model:
    """
    This class represents a OpenVINO model object.

    """
    def __init__(self, model_path, new_shape):
        """
        Initialize the model object
        
        Param: 
            model_path (string): path of inference model
            new_shape (dict): new shape of model input

        """
        self.model = ie_core.read_model(model=model_path)
        self.model.reshape(new_shape)
        self.compiled_model = ie_core.compile_model(model=self.model, device_name="CPU")
        self.output_layer = self.compiled_model.output(0)

    def predict(self, input_image):
        """
        Run inference
        
        Param: 
            input_image (np.array): input data
            
        Retuns:
            result (np.array)): model output data
        """
        result = self.compiled_model(input_image)[self.output_layer]
        return result

# 发信相关代码已移到 mailer.py：util 一被导入就会拉起 openvino，
# 而告警与设置对话框只需要发信能力，不应为此加载整个推理运行时。
