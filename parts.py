from enum import Enum
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation
from numpy import ndarray
from matplotlib.patches import Arc, Rectangle
from win32com.client import VARIANT, Dispatch, CDispatch
from pythoncom import VT_ARRAY, VT_R8, VT_DISPATCH
import math
import re
import os
import glob
import pandas as pd
from dataclasses import dataclass


def to_xyz(seq):
    if isinstance(seq, ndarray):
        seq = seq.tolist()
    if len(seq) == 2:
        x, y = seq
        z = 0
    elif len(seq) == 4:
        print(f'遇到可能是齐次变换的坐标：{seq}')
        seq = seq / seq[3]
        x, y, z, _ = seq
    else:
        x, y, z = seq
    return x, y, z


def aObjs(objs):
    return VARIANT(VT_ARRAY | VT_DISPATCH, objs)


def aPoint(x_or_seq, y=0, z=0):
    if isinstance(x_or_seq, (tuple, list, ndarray)):
        x, y, z = to_xyz(x_or_seq)
    else:
        x = x_or_seq
    return VARIANT(VT_ARRAY | VT_R8, (x, y, z))


def aDouble(xyz):
    if isinstance(xyz, ndarray):
        xyz = xyz.tolist()
    return VARIANT(VT_ARRAY | VT_R8, xyz)


@dataclass
class DrawedBearing:
    left_border: CDispatch = None
    right_border: CDispatch = None
    left_ball: CDispatch = None
    right_ball: CDispatch = None
    left_inner: CDispatch = None
    right_inner: CDispatch = None


class LayerType(Enum):
    SOLID = 'AM_0'
    DASHED = 'AM_3'
    DOTTED = 'AM_7'


class HatchType(Enum):
    SOLID = 'SOLID'
    NORMAL = 'ANSI31'


class Drawer:
    def __init__(self, acad=None):
        if acad is None:
            acad = Dispatch("AutoCAD.Application")
        self.doc = acad.ActiveDocument
        self.view = self.doc.ModelSpace
        self.acad_interface = acad

    def zoom_all(self):
        self.doc.Application.ZoomAll()

    def switch_layer(self, layer_type=LayerType.SOLID):
        ly = self.doc.Layers.Item(layer_type.value)
        self.doc.ActiveLayer = ly

    def arc(self, center, radius, start_angle, end_angle):
        start_angle = np.deg2rad(start_angle)
        end_angle = np.deg2rad(end_angle)
        return self.view.AddArc(aPoint(center), radius, start_angle, end_angle)

    def line(self, pt1, pt2):
        return self.view.AddLine(aPoint(pt1), aPoint(pt2))

    def circle(self, center, radius):
        return self.view.AddCircle(aPoint(center), radius)

    def rect(self, pt1, pt2):
        x1, y1, z1 = to_xyz(pt1)
        x2, y2, z2 = to_xyz(pt2)
        if z1 != z2:
            raise ValueError('非平面矩形！')
        pt_seq = sum((
            (x1, y1, z1), (x2, y1, z1),
            (x2, y2, z1), (x1, y2, z1),
            (x1, y1, z1)
        ), start=())
        return self.view.AddPolyline(aDouble(pt_seq))

    def polyline(self, *pts_list):
        pts = sum((
            tuple(pt) if isinstance(pt[0], (tuple, list))
            else (pt,) for pt in pts_list
        ), start=())
        pts = sum((
            to_xyz(pt) for pt in pts
        ), start=())
        return self.view.AddPolyline(aDouble(pts))

    def hatch(self, *objs, hatch_type=HatchType.NORMAL):
        hatch = self.view.AddHatch(0, hatch_type.value, True)
        for o in objs:
            if not isinstance(o, (tuple, list)):
                hatch.AppendOuterLoop(aObjs((o,)))
            else:
                hatch.AppendOuterLoop(aObjs(o))
        hatch.Evaluate()
        return hatch

    def random_spline(self, pt1, pt2, min_angle=10, max_angle=15):
        if np.random.rand() < 0.5:
            random_angle = np.random.randint(min_angle, max_angle)
        else:
            random_angle = np.random.randint(-max_angle, -min_angle)
        theta = np.deg2rad(random_angle)
        tang = np.asarray(pt2) - np.asarray(pt1)
        rotation_matrix = np.asarray([
            [np.cos(theta), -np.sin(theta)],
            [np.sin(theta), np.cos(theta)]
        ])
        startTang = (rotation_matrix @ tang).tolist()
        endTang = (rotation_matrix @ tang).tolist()
        startTang = aDouble(startTang + [0])
        endTang = aDouble(endTang + [0])
        pts = aDouble((*pt1, 0, *pt2, 0))
        return self.view.AddSpline(pts, startTang, endTang)


class Path:
    def __init__(self, start_pos=np.zeros(2)):
        if not isinstance(start_pos, ndarray):
            start_pos = np.array(start_pos)
        if len(start_pos) != 4:
            start_pos.resize(4)
            start_pos[-1] = 1
        self.points = [start_pos]

    def offset(self, x_or_seq, y=None):
        if y is not None:
            off = np.array((x_or_seq, y))
        elif not isinstance(x_or_seq, ndarray):
            off = np.array(x_or_seq)
        else:
            raise ValueError('offset不够')
        self.points.append(self.points[-1] + off)

    def draw(self, drawer: Drawer, transform=np.eye(4)):
        return drawer.polyline(
            transform @ pt for pt in self.points
        )


class Bearing:
    def __init__(self, code):
        self.code = code
        if code.startswith('16'):
            code = '0' + code[2:]
            bearing_type = '6'
        bearing_type = code[0]
        code = code[1:]
        match bearing_type:
            case '7':
                name = '角接触球轴承'
                if code.endswith('AC'):
                    angle = 25
                    code = code[:-2]
                elif code.endswith('B'):
                    angle = 40
                    code = code[:-1]
                elif code.endswith('C'):
                    angle = 15
                    code = code[:-1]
                else:
                    raise ValueError('角度信息缺失')
            case '6':
                name = '深沟球轴承'
                angle = None
            case _:
                raise ValueError('不支持的轴承类型')

        code = '7' + self.code[1:]
        size_df = pd.read_excel(r"D:\BaiduSyncdisk\球轴承尺寸.xlsx")
        codes = size_df[["a1", 'a2']]
        idx = codes.stack()[codes.stack() == '7000AC']
        if len(idx > 0):
            raise ValueError('错误的型号，多个值找到')
        idx = idx.index.tolist()[0][0]
        size_data = size_df.loc[idx, :]
        (
            self.d, self.da,
            self.b, self.c,
            self.c1
        ) = size_data[['d', 'D', 'B', 'c', 'c1']]

        self.name = name
        self.angle = angle

    @staticmethod
    def parse_code_size(digits):
        # 初始化变量
        A = B = C = D = None

        def get_size(d1, d2):
            d = int(d1) * 10 + int(d2)
            if d <= 3:
                d = [10, 12, 15, 17][d]
            else:
                d = d * 5
            return d

        # 匹配五位数字开头的情况：ABCDD
        five_digit_pattern = re.match(r'^(\d)(\d)(\d)(\d)$', digits)
        if five_digit_pattern:
            A, B, C, D1, D2 = five_digit_pattern.groups()
            A, B, C = int(A), int(B), int(C)
            D = get_size(D1, D2)
        # 匹配四位数开头的情况：ABDD
        else:
            four_digit_pattern = re.match(r'^(\d)(\d)(\d)$', digits)
            if four_digit_pattern:
                A, C, D1, D2 = four_digit_pattern.groups()
                A, C = int(A), int(C)
                B = 0 if C != 0 else 1
                D = get_size(D1, D2)
            # 匹配三位数开头并跟随一个斜杠和数值的情况：ABC/D
            else:
                three_digit_with_slash_pattern = re.match(
                    r'^(\d)(\d)/([\d.]+)$', digits)
                if three_digit_with_slash_pattern:
                    A, B, C, D = three_digit_with_slash_pattern.groups()
                    A, B, C = int(A), int(B), int(C)
                    D = float(D)

        # 返回结果
        return A, B, C, D

    def _draw_border(self, drawer: Drawer,
                     left_down: ndarray,
                     transform=np.eye(4)):
        """
        Draws bearing border with chamfers.
        Default model coordinate is defined as direction='UP';
        origin is left down point of the right rectangle boarder

        Params:
            drawer (object): The drawing tool or context to use for rendering the part.
            left_down (ndarray): The (x, y) coordinates for the left down point of the rect border.
            transform (ndarray): transform matrix

        Returns:
            objs (list[Dispatch])
        """
        length = (self.da - self.d) / 2
        path = Path(left_down + np.array((self.c, 0)))
        path.offset(length - self.c * 2, 0)
        path.offset(self.c, self.c)
        path.offset(0, self.b - self.c - self.c1)
        path.offset(-self.c1, self.c1)
        path.offset(self.c + self.c1 - length, 0)
        path.offset(0, self.c + self.c1 - self.b)
        path.offset(self.c, -self.c)
        return path.draw(drawer, transform)
    
    def _draw_inner(self, drawer: Drawer,
                     left_down: ndarray,
                     transform=np.eye(4)):
        """
        Draws the inner part of the bearing.

        Params:
            drawer (Drawer): The drawing tool or context to use for rendering the part.
            left_down (ndarray): The (x, y) coordinates for the left down point of the border.
            transform (ndarray): Transform matrix.

        Returns:
            objs (list[Dispatch]): List of drawn objects.
        """
        

    def draw(self, drawer, direction, center_pos):
        """
        Draws a part using the specified drawer, direction, and center position.

        Params:
            drawer (object): The drawing tool or context to use for rendering the part.
            direction (tuple): The direction vector in which to draw the part.
            for angular-contact bearings the direction is of its axial direction force;
            for deep grove ball bearings the direction is either of the two directions along the shaft.
            center_pos (tuple): The (x, y) coordinates for the center position of the part.

        Returns:
            objs (list[Dispatch])
        """
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)

        # get rotation angle from vector
        theta = np.arctan2(direction[0], direction[1])
        transform_mat = np.asarray([
            [np.cos(theta), -np.sin(theta), 0, center_pos[0]],
            [np.sin(theta), np.cos(theta), 0, center_pos[1]],
            [0, 0, 1, 0], [0, 0, 0, 1]
        ])  # 齐次变换
        mirror_mat = np.array([
            [-1, 0, 0, 0], [0, 1, 0, 0],
            [0, 0, 1, 0], [0, 0, 0, 1],
        ])

        res = DrawedBearing()

        # 画右边的部分
        pos = center_pos + np.array((self.d / 2, -self.b / 2))
        res.right_border = self._draw_border(drawer, pos, transform_mat)
        
        
        # 画左边的部分
        transform_mat = mirror_mat @ transform_mat
        pos = center_pos + np.array((-self.d / 2, -self.b / 2))
        res.left_border = self._draw_border(drawer, pos, transform_mat)


class Gear:
    def __init__(self, module, teeth_v, bold):
        self.diameter = teeth_v * module
        pitch_radius = module * teeth_v / 2
        self.d = pitch_radius
        self.df = pitch_radius + module      # 齿顶圆
        self.da = pitch_radius - 1.25*module  # 齿根圆
        self.bold = bold

    def draw(self, drawer):
        pass


get_R = {
    (0, 3): 0.2, (3, 6): 0.4,
    (6, 10): 0.6, (10, 18): 0.8,
    (18, 30): 1.0, (30, 50): 1.6,
    (50, 80): 2.0, (80, 120): 2.5,
    (120, 180): 3.0, (180, 250): 4.0,
    (250, 320): 5.0, (320, 400): 6.0,
    (400, 500): 8.0, (500, 630): 10,
    (630, 800): 12,  (800, 1000): 16,
    (1000, 1250): 20,  (1250, 1600): 25,
}


class Shaft:
    def __init__(self, initial_diameter=20.0, length=200.):
        self.initial_diameter = initial_diameter
        self.length = length
        self.steps = []          # [(位置, 直径)]
        self.shoulders = []      # [(位置, 高度, 宽度)]
        self.keyways = []        # [(位置, 长度, 宽度)]
        self.gears = []          # [(位置, 宽度, 直径)]

        self.chamfer_radius = 0  # 圆角半径
        for k, v in get_R.items():
            if initial_diameter <= k[1] and initial_diameter > k[0]:
                self.chamfer_radius = v
                break

        self.contour = []        # 原始轮廓
        self.chamfered_contour = []  # 倒角处理后的轮廓

        self.forces = {'y': [], 'z': []}    # 受力 [位置, 数量]
        self.bends = {'y': [], 'z': []}    # 受弯矩 [位置, 数量]
        self.twists = []                    # 受转矩

        self.bearing_pos = []
        self.coupling_pos = None

    def add_bearing(self, position, bearing):
        pass

    def add_step(self, position, diameter):
        self.steps.append((position, diameter))

    def add_shoulder(self, position, height, width):
        self.shoulders.append((position, height, width))

    def add_keyway(self, position, length, width):
        self.keyways.append((position, length, width))

    def add_gear(self, position, width, diameter, fr, ft, fa, bend_plane='z'):
        self.gears.append((position, width, diameter))

    def _get_diameter_at(self, pos, events):
        """核心方法：获取指定位置的直径"""
        # 按位置排序事件
        sorted_events = sorted(events, key=lambda x: x[0])
        current_diam = self.initial_diameter

        for event_pos, event_diam in sorted_events:
            if event_pos <= pos:
                current_diam = event_diam
            else:
                break  # 已过目标位置，提前终止
        return current_diam

    def process_features(self):
        events = []
        events.append((0, self.initial_diameter))

        # 处理阶梯特征
        current_diam = self.initial_diameter
        for pos, diam in self.steps:
            current_diam += diam
            events.append((pos, current_diam))

        # 转换轴肩特征
        for pos, height, width in self.shoulders:
            current_diam = self._get_diameter_at(pos, events)
            events.append((pos, current_diam + height))
            events.append((pos + width, current_diam))

        # 合并事件点
        events.sort(key=lambda x: x[0])
        merged = []
        last_pos = -np.inf
        for pos, diam in events:
            if pos > last_pos:
                merged.append((pos, diam))
                last_pos = pos
            else:
                merged[-1] = (pos, diam)

        # 生成基础轮廓
        self.contour = []
        current_diam = self.initial_diameter
        current_pos = 0
        self.contour.append((current_pos, current_diam))

        for pos, diam in merged:
            if pos <= current_pos:
                continue
            self.contour.extend([(pos, current_diam), (pos, diam)])
            current_diam = diam
            current_pos = pos

        # 末端延伸
        self.contour.append((self.length, current_diam))

        # 圆角处理
        self._apply_chamfers()

    def _apply_chamfers(self):
        """双圆角处理逻辑"""
        self.chamfered_contour = []

        for i in range(len(self.contour)-1):
            x0, d0 = self.contour[i]
            x1, d1 = self.contour[i+1]

            if x0 == x1:  # 垂直段（直径变化点）
                # 转换为半径单位进行计算
                r0 = d0 / 2
                r1 = d1 / 2
                delta_r = r1 - r0
                abs_radius = abs(self.chamfer_radius)

                # 内圆角（外侧）
                outer_cx = x0 + np.sign(delta_r) * abs_radius
                outer_cy = max(r0, r1) - abs_radius
                if delta_r > 0:
                    outer_theta = np.linspace(np.pi, np.pi / 2, 20)
                else:
                    outer_theta = np.linspace(np.pi / 2, 0, 20)

                # 外圆角（内侧）
                inner_cx = x0 - np.sign(delta_r) * abs_radius
                inner_cy = min(r0, r1) + abs_radius
                if delta_r > 0:
                    inner_theta = np.linspace(-np.pi / 2, 0, 20)
                else:
                    inner_theta = np.linspace(-np.pi, -np.pi / 2, 20)

                # 生成外圆角坐标（直径单位）
                outer_x = outer_cx + abs_radius * np.cos(outer_theta)
                outer_y = (outer_cy + abs_radius * np.sin(outer_theta)) * 2

                # 生成内圆角坐标（直径单位）
                inner_x = inner_cx + abs_radius * np.cos(inner_theta)
                inner_y = (inner_cy + abs_radius * np.sin(inner_theta)) * 2

                self.contour[i+1] = (x1 + abs_radius, d1)

                # 合并并排序坐标点
                if delta_r > 0:
                    combined = sorted(zip(inner_x, inner_y),
                                      key=lambda p: p[0])
                    combined += sorted(zip(outer_x, outer_y),
                                       key=lambda p: p[0])
                else:
                    combined = sorted(zip(outer_x, outer_y),
                                      key=lambda p: p[0])
                    combined += sorted(zip(inner_x, inner_y),
                                       key=lambda p: p[0])
                self.chamfered_contour.extend(combined)
            else:  # 水平段
                self.chamfered_contour.append((x0, d0))

        # 添加轮廓末端
        self.chamfered_contour.append(self.contour[-1])

    def plot(self, cad):
        if not self.chamfered_contour:
            self.process_features()

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.set_aspect('equal')

        # 处理倒角轮廓数据
        x = [p[0] for p in self.chamfered_contour]
        y = [p[1]/2 for p in self.chamfered_contour]  # 转换为半径

        # 绘制轮廓
        ax.plot(x, y, 'b-', lw=1.2, label='Shaft')
        ax.plot(x, [-v for v in y], 'b-', lw=1.2)
        ax.fill_between(x, y, [-v for v in y], color='skyblue', alpha=0.4)

        # 绘制受力
        for pos, val in self.forces['y']:
            draw_dir = (1 if val < 0 else -1) * self.length / 20
            ax.arrow(pos, 0, draw_dir, draw_dir, head_width=2,
                     head_length=4, fc='r', ec='r')
        for pos, val in self.forces['z']:
            draw_dir = (1 if val < 0 else -1) * self.length / 20
            ax.arrow(pos, 0, 0, draw_dir, head_width=2,
                     head_length=4, fc='r', ec='r')

        # 绘制 y 方向的弯矩
        for pos, val in self.bends['y']:
            # 生成圆弧的点
            if val > 0:
                theta = np.linspace(-np.pi / 2, 0, 100)
            else:
                theta = np.linspace(np.pi, np.pi / 2, 100)
            x = pos + 10 * np.cos(theta)
            # 为了区分 y 和 z 方向，将 z 方向的曲线在 y 轴上偏移
            y_offset = -12 if val > 0 else 10
            y = y_offset + 10 * np.sin(theta) / 2
            if val > 0:
                arror_d = (0, 1)
            else:
                arror_d = (1, 0)
            # 根据不同的 z 深度设置不同的颜色透明度，模拟 3D 效果
            alpha = 0.2 + \
                (pos / max([p for p, _ in self.bends['y'] + self.bends['z']])) * 0.8
            ax.plot(x, y, color='r', lw=2, alpha=alpha)
            arrow_start = (x[-1], y[-1])
            ax.arrow(arrow_start[0], arrow_start[1], arror_d[0], arror_d[1],
                     head_width=2, head_length=2, fc='r', ec='r')

        # 绘制 z 方向的弯矩
        for pos, val in self.bends['z']:
            # 生成圆弧的点
            if val > 0:
                theta = np.linspace(-np.pi / 2, 0, 100)
            else:
                theta = np.linspace(np.pi, np.pi / 2, 100)
            x = pos + 10 * np.cos(theta)
            y = 10 * np.sin(theta)
            if val > 0:
                arror_d = (0, 1)
            else:
                arror_d = (1, 0)
            # 根据不同的 z 深度设置不同的颜色透明度，模拟 3D 效果
            alpha = 0.2 + \
                (pos / max([p for p, _ in self.bends['y'] + self.bends['z']])) * 0.8
            ax.plot(x, y, color='r', lw=2, alpha=alpha)
            arrow_start = (x[-1], y[-1])
            ax.arrow(arrow_start[0], arrow_start[1], arror_d[0], arror_d[1],
                     head_width=3, head_length=4, fc='r', ec='r')

        # 绘制半圆形键槽
        for pos, length, width in self.keyways:
            # 绘制上侧线段
            ax.plot([pos, pos + length], [width / 2, width / 2], 'r-', lw=2)
            # 绘制下侧线段
            ax.plot([pos, pos + length], [-width / 2, -width / 2], 'r-', lw=2)

            # 绘制左侧半圆
            left_arc = Arc((pos, 0), width, width, theta1=90,
                           theta2=270, edgecolor='red', lw=2)
            ax.add_patch(left_arc)

            # 绘制右侧半圆
            right_arc = Arc((pos + length, 0), width, width,
                            theta1=-90, theta2=90, edgecolor='red', lw=2)
            ax.add_patch(right_arc)

        # 绘制齿轮
        for pos, width, diameter in self.gears:
            gear = Rectangle((pos, -diameter/2), width,
                             diameter, fc='orange', alpha=0.5)
            ax.add_patch(gear)

        # 绘制联轴器
        if self.coupling_pos is not None:
            coupling = Rectangle((self.coupling_pos - 5, -self.initial_diameter/2),
                                 10, self.initial_diameter, fc='green', alpha=0.5)
            ax.add_patch(coupling)

        plt.title("Improved Shaft Visualization")
        plt.xlabel("X (mm)")
        plt.ylabel("Y (mm)")
        plt.grid(True)
        return fig
