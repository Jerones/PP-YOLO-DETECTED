# -*- coding: utf-8 -*-
"""读数历史数据看板。

相比原来「空画布 + 手动选文件」的做法，这里补上：
- 自动扫描 csv_data 下的历史文件，默认选中最新一天
- 指标概览：样本数、时间跨度、均值、峰值、谷值、越限次数
- 阈值虚线与越限点高亮，异常时段一眼可见
- 大数据量降采样（min/max 包络），几十万点也不会卡死，且不丢尖峰
- 多表分线绘制
- 导出图表与筛选后的数据
"""

import os

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from settings import MODE_VALUE, AppSettings

# 中文标签需要中文字体，否则坐标轴会显示成方框
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

# 画布最多绘制的点数。超采样后按 min/max 包络压缩，保留极值形态
MAX_PLOT_POINTS = 4000

RANGES = [('全部数据', None), ('最近 1 小时', 3600), ('最近 24 小时', 86400),
          ('最近 7 天', 7 * 86400)]

LINE_COLORS = ['#1668DC', '#12A594', '#C4320A', '#7C4DFF', '#0F9D58']

KPI_LABELS = ['样本数', '时间跨度', '均值', '峰值', '谷值', '越限次数']


def _read_csv(path):
    """读 CSV，兼容 Excel 另存出来的编码。

    程序自己写的是 UTF-8，但用户用 Excel 打开再保存时，中文 Windows 会写成
    GBK，直接按 UTF-8 读会抛 UnicodeDecodeError。按常见顺序回退即可。
    """
    last = None
    for encoding in ('utf-8-sig', 'gbk'):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last = exc
    raise last


def load_table(path):
    """读取一个 CSV，兼容旧的两列格式 (time,scale)。"""
    data = _read_csv(path)
    if 'time' not in data.columns or 'scale' not in data.columns:
        raise ValueError("缺少 time 或 scale 列")
    if 'meter_id' not in data.columns:
        data['meter_id'] = 1
    if 'range' not in data.columns:
        data['range'] = np.nan
    if 'unit' not in data.columns:
        data['unit'] = 'MPa'
    data['time'] = pd.to_datetime(data['time'], errors='coerce')
    data['scale'] = pd.to_numeric(data['scale'], errors='coerce')
    data = data.dropna(subset=['time', 'scale']).sort_values('time')
    return data.reset_index(drop=True)


def envelope(times, values, max_points=MAX_PLOT_POINTS):
    """按桶取 min/max 包络降采样。

    等间隔抽样会漏掉尖峰，而尖峰恰恰是最需要看到的异常。
    每个桶保留最小值和最大值两点，曲线形态与极值都不丢。
    """
    count = len(values)
    if count <= max_points:
        return times, values
    buckets = max(1, max_points // 2)
    edges = np.linspace(0, count, buckets + 1).astype(int)
    out_t, out_v = [], []
    for index in range(buckets):
        start, end = edges[index], edges[index + 1]
        if end <= start:
            continue
        segment = values[start:end]
        low_at = start + int(np.argmin(segment))
        high_at = start + int(np.argmax(segment))
        # 按时间顺序输出，否则折线会来回穿插
        for pos in sorted({low_at, high_at}):
            out_t.append(times[pos])
            out_v.append(values[pos])
    return out_t, out_v


def format_span(seconds):
    if seconds is None or not np.isfinite(seconds) or seconds <= 0:
        return '—'
    seconds = int(seconds)
    if seconds < 60:
        return '{} 秒'.format(seconds)
    if seconds < 3600:
        return '{} 分 {} 秒'.format(seconds // 60, seconds % 60)
    if seconds < 86400:
        return '{} 小时 {} 分'.format(seconds // 3600, seconds % 3600 // 60)
    return '{} 天 {} 小时'.format(seconds // 86400, seconds % 86400 // 3600)


class KpiCard(QtWidgets.QFrame):
    """指标卡：上方浅色标题，下方深色数值。"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName('kpiCard')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.titleLabel = QtWidgets.QLabel(title)
        self.titleLabel.setObjectName('kpiTitle')
        self.valueLabel = QtWidgets.QLabel('—')
        self.valueLabel.setObjectName('kpiValue')
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.valueLabel)

    def set_value(self, text, color=None):
        self.valueLabel.setText(text)
        if color:
            self.valueLabel.setStyleSheet('color: {};'.format(color))


class DataBoard(QtWidgets.QWidget):
    """读数历史看板。"""

    def __init__(self, csv_dir, settings=None, parent=None):
        super().__init__(parent)
        self.csv_dir = csv_dir
        # 与主窗口共用同一个设置对象：主界面改了阈值，看板重绘即可同步
        self.settings = settings or AppSettings()
        self.setWindowTitle('数据分析')
        self.resize(1160, 720)
        self._data = None
        self._current_path = None
        self._last_refresh = 0.0

        self._build_ui()
        self.refresh_files(select_latest=True)

    # ---------------- 界面 ----------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # 工具条
        bar = QtWidgets.QFrame()
        bar.setObjectName('toolBarCard')
        bar_layout = QtWidgets.QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(10)

        title = QtWidgets.QLabel('读数历史')
        title.setObjectName('boardTitle')
        bar_layout.addWidget(title)

        bar_layout.addSpacing(8)
        bar_layout.addWidget(QtWidgets.QLabel('数据源'))
        self.fileBox = QtWidgets.QComboBox()
        self.fileBox.setMinimumWidth(220)
        self.fileBox.currentIndexChanged.connect(self._on_file_changed)
        bar_layout.addWidget(self.fileBox)

        bar_layout.addWidget(QtWidgets.QLabel('时间范围'))
        self.rangeBox = QtWidgets.QComboBox()
        for name, _ in RANGES:
            self.rangeBox.addItem(name)
        self.rangeBox.currentIndexChanged.connect(self.redraw)
        bar_layout.addWidget(self.rangeBox)

        self.refreshButton = QtWidgets.QPushButton('刷新')
        self.refreshButton.setObjectName('boardAction')
        self.refreshButton.clicked.connect(lambda: self.refresh_files())
        bar_layout.addWidget(self.refreshButton)

        bar_layout.addStretch(1)
        self.exportImageButton = QtWidgets.QPushButton('导出图表')
        self.exportImageButton.setObjectName('boardAction')
        self.exportImageButton.clicked.connect(self.export_image)
        bar_layout.addWidget(self.exportImageButton)
        self.exportCsvButton = QtWidgets.QPushButton('导出数据')
        self.exportCsvButton.setObjectName('boardAction')
        self.exportCsvButton.clicked.connect(self.export_csv)
        bar_layout.addWidget(self.exportCsvButton)
        root.addWidget(bar)

        # 指标卡
        kpi_row = QtWidgets.QHBoxLayout()
        kpi_row.setSpacing(12)
        self.kpis = {}
        for name in KPI_LABELS:
            card = KpiCard(name)
            self.kpis[name] = card
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        # 画布
        canvas_card = QtWidgets.QFrame()
        canvas_card.setObjectName('canvasCard')
        canvas_layout = QtWidgets.QVBoxLayout(canvas_card)
        canvas_layout.setContentsMargins(10, 10, 10, 10)
        self.canvas = FigureCanvas(Figure(figsize=(9, 4.6), dpi=100))
        canvas_layout.addWidget(self.canvas)
        root.addWidget(canvas_card, 1)

        self.statusLabel = QtWidgets.QLabel('')
        self.statusLabel.setObjectName('boardStatus')
        root.addWidget(self.statusLabel)

        self.ax = self.canvas.figure.add_subplot(111)
        self._draw_empty('暂无数据')

    # ---------------- 数据加载 ----------------

    def _csv_files(self):
        if not os.path.isdir(self.csv_dir):
            return []
        files = [name for name in os.listdir(self.csv_dir)
                 if name.lower().endswith('.csv')]
        # 文件名以日期开头，倒序即最新的在前
        return sorted(files, reverse=True)

    def refresh_files(self, select_latest=False):
        """重新扫描数据目录。检测过程中会产生新文件，需要能刷出来。"""
        previous = self.fileBox.currentText()
        files = self._csv_files()
        self.fileBox.blockSignals(True)
        self.fileBox.clear()
        self.fileBox.addItems(files if files else ['（无数据文件）'])
        self.fileBox.blockSignals(False)
        if not files:
            self._data = None
            self._reset_kpis()
            self._draw_empty('目录中没有 CSV 数据：{}'.format(self.csv_dir))
            self.statusLabel.setText('提示：先打开摄像头做一次检测，数据会自动写入该目录')
            return
        if select_latest:
            self.fileBox.setCurrentIndex(0)
        elif previous in files:
            self.fileBox.setCurrentIndex(files.index(previous))
        self._load(self.fileBox.currentText())

    def _on_file_changed(self, _index):
        name = self.fileBox.currentText()
        if name and not name.startswith('（'):
            self._load(name)

    def _load(self, name):
        path = os.path.join(self.csv_dir, name)
        try:
            self._data = load_table(path)
            self._current_path = path
        except Exception as exc:
            self._data = None
            self._reset_kpis()
            self._draw_empty('读取失败：{}'.format(exc))
            self.statusLabel.setText(path)
            return
        self.redraw()

    def auto_refresh(self):
        """检测过程中由主窗口调用：有新文件或当前文件变大时刷新。"""
        files = self._csv_files()
        if not files:
            return
        current = self.fileBox.currentText()
        newest = files[0]
        # 跨天时新文件出现，自动切过去；否则只在当前文件有更新时重绘
        if newest != current and self.fileBox.count() != len(files):
            self.refresh_files(select_latest=True)
            return
        if current == newest:
            path = os.path.join(self.csv_dir, current)
            if not os.path.isfile(path):
                return
            if self._current_path and os.path.getsize(path) != getattr(
                    self, '_last_size', -1):
                self._last_size = os.path.getsize(path)
                self._load(current)

    # ---------------- 绘图 ----------------

    def _reset_kpis(self):
        for card in self.kpis.values():
            card.set_value('—', '#26364D')

    def _style_axes(self):
        ax = self.ax
        ax.set_facecolor('#FFFFFF')
        for spine in ('top', 'right'):
            ax.spines[spine].set_visible(False)
        for spine in ('left', 'bottom'):
            ax.spines[spine].set_color('#DCE2EC')
        ax.grid(True, color='#EEF2F8', linewidth=0.9)
        ax.set_axisbelow(True)
        ax.tick_params(colors='#6C7A8D', labelsize=9)
        self.canvas.figure.patch.set_facecolor('#FFFFFF')

    def _draw_empty(self, message):
        self.ax.clear()
        self._style_axes()
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in ('left', 'bottom'):
            self.ax.spines[spine].set_visible(False)
        self.ax.text(0.5, 0.5, message, ha='center', va='center',
                     fontsize=11, color='#93A0B4', transform=self.ax.transAxes)
        self.canvas.draw_idle()

    def _filtered(self):
        data = self._data
        if data is None or data.empty:
            return None
        seconds = RANGES[self.rangeBox.currentIndex()][1]
        if seconds:
            latest = data['time'].max()
            data = data[data['time'] >= latest - pd.Timedelta(seconds=seconds)]
        return data if not data.empty else None

    def has_data(self):
        """是否已经加载了可用于绘制的数据。"""
        return self._data is not None and not self._data.empty

    def redraw(self):
        data = self._filtered()
        if data is None:
            self._reset_kpis()
            self._draw_empty('所选时间范围内没有数据')
            return

        self.ax.clear()
        self._style_axes()

        groups = list(data.groupby('meter_id'))
        multi = len(groups) > 1
        exceeded = 0
        has_threshold = False
        exceeded_legend = False

        for order, (meter_id, group) in enumerate(groups):
            color = LINE_COLORS[order % len(LINE_COLORS)]
            threshold, inferred = self._threshold_of(group)
            times = list(group['time'])
            values = list(group['scale'])
            times, values = envelope(times, values)
            label = '表计 {}'.format(meter_id) if multi else '读数'
            self.ax.plot(times, values, color=color, linewidth=1.4,
                         label=label, solid_joinstyle='round')
            if threshold is None:
                continue
            has_threshold = True
            bad = group[group['scale'] < threshold]
            exceeded += len(bad)
            if not bad.empty:
                # 越限点只在第一次出现时进图例，避免多表时图例项翻倍
                self.ax.scatter(bad['time'], bad['scale'], s=16,
                                color='#D9534F', zorder=3, edgecolors='none',
                                label='越限点' if not exceeded_legend else '_nolegend_')
                exceeded_legend = True
            # 单表用醒目的红色虚线；多表时用与曲线同色，避免几条红线分不清
            self.ax.axhline(threshold, color='#D9534F' if not multi else color,
                            linestyle='--', linewidth=1.2, alpha=0.85,
                            label='{}告警下限 {:.2f}{}'.format(
                                '' if not multi else '表计 {} '.format(meter_id),
                                threshold, '（推断）' if inferred else ''))

        self.ax.set_title('表计读数随时间变化', fontsize=12, color='#17233B',
                          pad=12, loc='left')
        self.ax.set_xlabel('时间', fontsize=9.5, color='#6C7A8D')
        self.ax.set_ylabel('读数', fontsize=9.5, color='#6C7A8D')
        if has_threshold or multi:
            # 多表时曲线通常分布在两端，中部是空白，图例放右侧居中不会压数据。
            # 但曲线走势不可预知（例如某块表后段骤降），实测会正好穿过图例文字，
            # 因此给图例加一层近乎不透明的白底：即使压住曲线，文字仍然清晰。
            legend = self.ax.legend(
                loc='center right', fontsize=8.5, frameon=True,
                facecolor='#FFFFFF', edgecolor='#E4EAF3', framealpha=0.94,
                borderpad=0.7, labelspacing=0.5, handlelength=2.2)
            legend.get_frame().set_linewidth(0.8)
            for text in legend.get_texts():
                text.set_color('#3C4A5F')
        # autofmt_xdate 已经处理了日期标签的旋转与留白，再调 tight_layout 会告警
        self.canvas.figure.autofmt_xdate(rotation=20, ha='right')
        self.canvas.draw_idle()

        self._update_kpis(data, has_threshold, exceeded)
        self.statusLabel.setText(
            '{}  ·  共 {} 条记录  ·  绘制 {} 个点'.format(
                os.path.basename(self._current_path or ''),
                len(data), min(len(data), MAX_PLOT_POINTS)))

    def _threshold_of(self, group):
        """返回 (告警下限, 是否为推断值)。

        阈值来源与实时告警完全一致（同一个 settings 对象）：
        自定义读数时全表统一取值，百分比模式才需要量程；旧格式没有量程列
        时按读数水平反推表型——两种表量程相差 15 倍，读数区间几乎不重叠。
        """
        settings = self.settings
        if settings.threshold_mode == MODE_VALUE:
            return float(settings.alarm_value), False
        ratio = settings.alarm_ratio
        ranges = group['range'].dropna()
        if not ranges.empty and ranges.iloc[-1] > 0:
            return float(ranges.iloc[-1]) * ratio, False
        high = float(group['scale'].quantile(0.9))
        if high <= 0:
            return None, False
        return (25.0 if high > 2.5 else 1.6) * ratio, True

    def _update_kpis(self, data, has_threshold, exceeded):
        values = data['scale']
        span = (data['time'].max() - data['time'].min()).total_seconds()
        self.kpis['样本数'].set_value('{:,}'.format(len(data)))
        self.kpis['时间跨度'].set_value(format_span(span))
        self.kpis['均值'].set_value('{:.3f}'.format(values.mean()))
        self.kpis['峰值'].set_value('{:.3f}'.format(values.max()))
        self.kpis['谷值'].set_value('{:.3f}'.format(values.min()))
        if not has_threshold:
            self.kpis['越限次数'].set_value('—', '#26364D')
        else:
            self.kpis['越限次数'].set_value(
                '{:,}'.format(exceeded), '#D9534F' if exceeded else '#12A594')

    # ---------------- 导出 ----------------

    def export_image(self):
        if self._data is None:
            QMessageBox.information(self, '提示', '当前没有可导出的图表。')
            return
        default = '读数曲线.png'
        path, _ = QFileDialog.getSaveFileName(
            self, '导出图表', default, 'PNG 图片 (*.png);;PDF 文件 (*.pdf)')
        if not path:
            return
        try:
            self.canvas.figure.savefig(path, dpi=160, bbox_inches='tight',
                                       facecolor='#FFFFFF')
        except Exception as exc:
            QMessageBox.warning(self, '导出失败', str(exc))
            return
        self.statusLabel.setText('图表已导出：{}'.format(path))

    def export_csv(self):
        data = self._filtered()
        if data is None:
            QMessageBox.information(self, '提示', '当前没有可导出的数据。')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '导出数据', '读数数据.csv', 'CSV 文件 (*.csv)')
        if not path:
            return
        try:
            data.to_csv(path, index=False, encoding='utf-8-sig')
        except Exception as exc:
            QMessageBox.warning(self, '导出失败', str(exc))
            return
        self.statusLabel.setText('数据已导出：{}'.format(path))
