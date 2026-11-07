# 模型权重（不在本仓库内）

## 为什么没有

| 文件 | 大小 |
|---|---|
| `model/meter_det_model/model.pdiparams` | 207 MB |
| `model/meter_seg_model/model.pdiparams` | 103 MB |

GitHub 对单文件有 100 MB 的硬限制（超了会直接拒绝推送），普通仓库也不适合塞 300 MB 二进制。
所以 `.gitignore` 排除了全部权重文件，仓库里只保留本说明。

下完权重放到 `model/` 下，程序即可运行；本机的 `model/` 目录已经有文件，只是不会被提交。

## 需要放成什么结构

```
model/
├── meter_det_model/          # 表计检测：PPYOLOv2，输入 608×608
│   ├── model.pdmodel
│   ├── model.pdiparams
│   └── model.yml
└── meter_seg_model/          # 表盘分割：DeepLabV3P，输入 512×512
    ├── model.pdmodel
    ├── model.pdiparams
    └── model.yml
```

必须是**导出的 inference model**（`model.pdmodel` + `model.pdiparams`），
不是训练权重 `.pdparams`。程序通过 OpenVINO 的 Paddle 前端直接读这两个文件，
所以不需要再装 PaddlePaddle。

## 获取方式一：官方预训练模型（最快）

PaddleX 的 meter_reader 示例提供了这两个模型，可以直接下载后改名放入：

```bash
# 在项目根目录执行
curl -O https://bj.bcebos.com/paddlex/examples2/meter_reader/meter_det_model.tar.gz
curl -O https://bj.bcebos.com/paddlex/examples2/meter_reader/meter_seg_model.tar.gz
tar -xzf meter_det_model.tar.gz && tar -xzf meter_seg_model.tar.gz
```

解压后把 `meter_det_model/`、`meter_seg_model/` 整个搬到本目录下即可。
官方模型是通用表计模型，读数精度不如本项目微调后的版本，但足以跑通流程。

## 获取方式二：自己训练导出

`notebooks/基于PP-YOLO.ipynb` 记录了完整流程（PaddleDetection 训练 PPYOLOv2 检测、
PaddleSeg 训练 DeepLabV3P 分割、`export.py` 导出 inference model）。
训练权重对应约 2 万张表计标注图，导出后的目录结构与上面一致。

## 校验是否放对了

```bash
python -c "import pre; pre.warmup(); print('模型加载成功')"
```

或者直接运行程序，用 `data/meter_test/` 里的样图点一次「图片检测」，
能画出表盘框并给出读数即为正常。
