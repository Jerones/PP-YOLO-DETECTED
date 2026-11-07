# -*- coding: utf-8 -*-
"""读数落盘。

CSV 列格式：time, meter_id, scale, range, unit
- 兼容旧数据：早期文件只有 time,scale 两列，读取方需自行补默认值
- 按表分列记录：原来只写 readings[0]，多块表时其余读数直接丢失

写入节流：检测约 1 秒一帧，若每帧都写，一天约 8.6 万行且全是重复值。
改为「每块表最多每秒一条」，并只写入平滑后的稳定值。

告警判定不在这里：发信规则（只发一封、需手动重置）由 alarm.AlarmCenter
负责，本模块只管把读数落到 CSV。
"""

import csv
import os
import threading
import time

# 同一块表两次写盘的最小间隔（秒）
RECORD_INTERVAL = 1.0

CSV_HEADER = ['time', 'meter_id', 'scale', 'range', 'unit']


class ReadingRecorder:
    """按表记录读数到按天切分的 CSV 文件。"""

    def __init__(self, csv_dir, record_interval=RECORD_INTERVAL):
        self.csv_dir = csv_dir
        self.record_interval = record_interval
        self._last_written = {}     # meter_id -> 上次写盘时间
        self._lock = threading.Lock()
        self.last_error = None

    def reset(self):
        with self._lock:
            self._last_written.clear()

    def feed(self, meters, now=None):
        """处理一帧平滑后的结果。

        返回本帧新写入的记录列表，每项形如
        {'time','meter_id','scale','range','unit'}。
        """
        now = time.time() if now is None else now
        written = []
        for meter in meters:
            if not meter.get('stable') or meter.get('smoothed') is None:
                continue
            meter_id = meter.get('index', 1)
            if self._should_write(meter_id, now):
                written.append(self._write(meter, meter_id, now))
        return written

    def _should_write(self, meter_id, now):
        with self._lock:
            last = self._last_written.get(meter_id, 0.0)
            if now - last < self.record_interval:
                return False
            self._last_written[meter_id] = now
            return True

    def _write(self, meter, meter_id, now):
        record = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
            'meter_id': meter_id,
            'scale': round(float(meter['smoothed']), 6),
            'range': meter.get('range', ''),
            'unit': meter.get('unit', 'MPa'),
        }
        day = time.strftime('%Y-%m-%d', time.localtime(now))
        try:
            os.makedirs(self.csv_dir, exist_ok=True)
            path = self._resolve_path(os.path.join(self.csv_dir, day + '.csv'))
            # 每次追加都重新打开：进程可能在检测中途被关闭，
            # 保持短连接可以避免文件句柄残留和缓冲区丢数据
            with open(path, mode='a', newline='', encoding='utf-8') as handle:
                writer = csv.writer(handle)
                if handle.tell() == 0:
                    writer.writerow(CSV_HEADER)
                writer.writerow([record['time'], record['meter_id'],
                                 record['scale'], record['range'], record['unit']])
        except OSError as exc:
            self.last_error = str(exc)
        return record

    def _resolve_path(self, path):
        """旧格式文件（time,scale）无法容纳新列，改写到 _v2 文件，避免列错位。"""
        header = self._read_header(path)
        if header is not None and header != CSV_HEADER:
            base, ext = os.path.splitext(path)
            return base + '_v2' + ext
        return path

    @staticmethod
    def _read_header(path):
        if not os.path.isfile(path):
            return None
        try:
            with open(path, mode='r', newline='', encoding='utf-8') as handle:
                return next(csv.reader(handle), None)
        except OSError:
            return None
