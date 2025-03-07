from enum import Enum
import math
import re
import warnings
from dataclasses import dataclass

import numpy as np
from numpy import ndarray
from win32com.client import CDispatch
import pandas as pd

from drawer import (
    Drawer, Path2D, LayerType
)


class BadDesignWarning(UserWarning):
    pass


class Angle:
    def __init__(self, degrees):
        # 初始化角度值，以度为单位
        self._degrees = degrees

    def __repr__(self):
        # 输出时只输出角度值
        return f'A({self._degrees})'

    def __str__(self):
        # 字符串表示，输出度分秒
        degrees = self._degrees
        deg = int(degrees)
        minutes = (degrees - deg) * 60
        min = int(minutes)
        seconds = (minutes - min) * 60
        return f"{deg}°{min}'{seconds : <.2f}″"

    def __float__(self):
        # 数字表示，输出角度值
        return float(self._degrees)

    def to_radians(self):
        # 将角度转换为弧度
        return math.radians(self._degrees)

    def sin(self):
        # 计算正弦值
        return math.sin(self.to_radians())

    def cos(self):
        # 计算余弦值
        return math.cos(self.to_radians())

    def tan(self):
        return math.tan(self.to_radians())


@dataclass
class DrawedBearing:
    left_border: CDispatch = None
    right_border: CDispatch = None
    left_inner: list[CDispatch] = None
    right_inner: list[CDispatch] = None
    hatch_right: CDispatch = None
    wipeout: CDispatch = None


class Bearing:
    size_df = pd.read_excel(r"D:\BaiduSyncdisk\球轴承尺寸.xlsx")

    def __init__(self, code):
        self.code = code
        if code.startswith('16'):
            bearing_type = '6'
        else:
            bearing_type = code[0]
        match bearing_type:
            case '7':
                name = '角接触球轴承'
                if code.endswith('AC'):
                    angle = 25
                elif code.endswith('B'):
                    raise ValueError('不支持B型角接触球轴承')
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
        codes = Bearing.size_df[["a1", 'a2']]
        idx = codes.stack()[codes.stack() == code]
        idx = list(set(i[0] for i in idx.index))
        if len(idx) > 1:
            raise ValueError(f'错误的型号，多个值找到：{idx}')
        elif len(idx) == 0:
            raise ValueError(f'错误的型号，未找到：{code}')
        size_data = Bearing.size_df.loc[idx[0], :]
        (
            self.d, self.da,
            self.b, self.c,
            self.c1
        ) = size_data[['d', 'D', 'B', 'c', 'c1']]

        self.name = name
        self.angle = np.deg2rad(angle) if angle is not None else 0

        length = (self.da - self.d) / 2
        ball_radius = length / 4
        self.inner_thick = length / 2 - ball_radius * np.cos(np.pi / 3)

    def check_attach(self, height):
        if height > self.inner_thick * 4 / 5:
            warnings.warn(
                f'高度 {height} 超过了轴承内圈厚度的 4/5', BadDesignWarning)
            return False
        return True

    def __repr__(self):
        return f'Bearing({self.code})'

    def __str__(self):
        return f'{self.name} {self.code} {self.d}x{self.da}x{self.b}'

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
                     left_down: ndarray):
        """
        绘制带倒角的轴承边界。
        默认模型坐标定义为方向='UP';
        原点是右矩形边界的左下点

        参数:
            drawer (object): 用于渲染零件的绘图工具或上下文。
            left_down (ndarray): 矩形边界左下点的 (x, y) 坐标。
            transform (ndarray): 变换矩阵

        返回:
            objs (list[Dispatch])
        """
        length = (self.da - self.d) / 2
        path = Path2D(left_down + np.array((self.c, 0)))
        path.offset(length - self.c * 2, 0)
        path.offset(self.c, self.c)
        path.offset(0, self.b - self.c - self.c1)
        path.offset(-self.c1, self.c1)
        path.offset(self.c + self.c1 - length, 0)
        path.offset(-self.c, -self.c)
        path.offset(0, self.c * 2 - self.b)
        path.offset(self.c, -self.c)
        drawer.switch_layer(LayerType.SOLID)
        return path.draw(drawer)

    def _draw_inner(self, drawer: Drawer,
                    left_down: ndarray,
                    simplified: bool = False,
                    border_objs=None):
        """
        绘制轴承的内部部分。

        参数:
            drawer (Drawer): 用于渲染零件的绘图工具或上下文。
            left_down (ndarray): 边界左下点的 (x, y) 坐标。
            transform (ndarray): 变换矩阵。

        返回:
            objs (list[Dispatch]): 绘制的对象列表。
        """
        if not isinstance(left_down, ndarray):
            left_down = np.array(left_down, dtype=np.floating)
        length = (self.da - self.d) / 2
        center = left_down + np.array((length / 2, self.b / 2))
        if not simplified:
            drawer.switch_layer(LayerType.SOLID)
            # 非简化画法
            radius = length / 4
            half_b = self.b / 2
            xoff = radius * np.cos(np.pi / 3)
            yoff = radius * np.sin(np.pi / 3)
            points = (
                (-xoff, -half_b), (-xoff, -yoff),  # 左下
                (-xoff, half_b), (-xoff, yoff),  # 左上
                (xoff, -half_b), (xoff, -yoff),  # 右下
                (xoff, yoff),  # 右上
                (xoff + (half_b - yoff) * np.sin(np.deg2rad(33)), half_b)
            ) + center
            points = points.reshape(-1, 2, 2)
            objs = []
            for start, end in points:
                objs.append(drawer.line(start, end))
            objs.append(drawer.circle(center, radius))
            if border_objs is not None:
                aux_arc1 = drawer.arc(center, radius, -60, 60)
                aux_arc2 = drawer.arc(center, radius, 120, 240)
                aux_line1 = drawer.line(points[0][0], points[2][0])
                aux_line2 = drawer.line(points[1][0], points[3][1])
                drawer.switch_layer(LayerType.THIN)
                ht = drawer.hatch(border_objs, inner_objs=[[
                    *objs[:-1], aux_arc1,  aux_arc2, aux_line1, aux_line2
                ]])
                for obj in (aux_arc1, aux_arc2, aux_line1, aux_line2):
                    obj.Delete()
            else:
                ht = None
            return objs, ht
        else:
            drawer.switch_layer(LayerType.THIN)
            angle_vec = np.array((
                np.sin(self.angle) * length / 3,
                np.cos(self.angle) * length / 3
            ))
            vert_angle = self.angle + np.pi / 2
            vert_vec = np.array((
                np.sin(vert_angle) * self.b / 8,
                np.cos(vert_angle) * self.b / 8
            ))
            start = center + angle_vec
            end = center - angle_vec
            objs = [drawer.line(start, end)]
            start = center + vert_vec
            end = center - vert_vec
            objs.append(drawer.line(start, end))
            return objs

    def _draw_side(self, drawer: Drawer,
                   center_pos: ndarray):
        # 画右边的部分
        pos = center_pos + np.array((self.d / 2, -self.b / 2))
        rb = self._draw_border(drawer, pos)
        ri, ht = self._draw_inner(drawer, pos,
                                  False, rb)

        # 画左边的部分
        with drawer.transformed(mirrored_axis='y'):
            lb = self._draw_border(drawer, pos)
            li = self._draw_inner(drawer, pos, True)

        return rb, ri, ht, lb, li

    def draw(self, drawer: Drawer,
             center_pos: ndarray,
             direction: ndarray):
        """
        使用指定的绘图工具、方向和中心位置绘制零件。

        参数:
            drawer (object): 用于渲染零件的绘图工具或上下文。
            direction (tuple): 绘制零件的方向向量。
            对于角接触轴承，方向是其轴向力的方向；
            对于深沟球轴承，方向是沿轴的两个方向之一。
            center_pos (tuple): 零件中心位置的 (x, y) 坐标。

        返回:
            objs (list[Dispatch])
        """
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)

        # get rotation angle from vector
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            res = DrawedBearing()

            wipe_region = Path2D((-self.da / 2 + self.c, -self.b / 2))
            wipe_region.offset(self.da - self.c * 2, 0)
            wipe_region.offset(self.c, self.c)
            wipe_region.offset(0, self.b - self.c - self.c1)
            wipe_region.offset(-self.c1, self.c1)
            wipe_region.offset(-self.da + self.c1 * 2, 0)
            wipe_region.offset(-self.c1, -self.c1)
            wipe_region.offset(0, -self.b + self.c1 + self.c)
            wipe_region.offset(self.c, -self.c)
            drawer.switch_layer(LayerType.SOLID)
            res.wipeout = wipe_region.wipeout(drawer)

            (
                res.right_border, res.right_inner,
                res.hatch_right,
                res.left_border, res.left_inner
            ) = self._draw_side(drawer, (0, 0))

            return res


@dataclass
class DrawedGear:
    right: list[CDispatch] = None
    left: list[CDispatch] = None
    left_hatch: CDispatch = None
    right_hatch: CDispatch = None
    left_axis: CDispatch = None
    right_axis: CDispatch = None
    wipeout: CDispatch = None


class GearRotation(Enum):
    CLOCKWISE = 1
    COUTER_CLOCKWISE = 2
    NONE = 3


class Gear:
    def __init__(self, module, teeth, bold, d_hole,
                 rot_dir=GearRotation.NONE,
                 beta: Angle = Angle(0)):
        teeth_v = teeth / (beta.cos()**3)
        self.diameter = teeth_v * module
        pitch_diameter = module * teeth_v
        self.r = pitch_diameter / 2
        self.ra = pitch_diameter / 2 + module
        self.rf = pitch_diameter / 2 - 1.25 * module
        self.half_bold = bold / 2
        self.r_hole = d_hole / 2
        self.angle = beta.to_radians()
        self.rotation = rot_dir
        self.c_outer = module
        self.c_inner = Shaft._get_chamfer_radius(self.r_hole)

    def _draw_half(self, drawer: Drawer, is_second=False):
        bold = self.half_bold * 2

        path = Path2D((self.ra - self.c_outer, self.half_bold))
        path.offset(self.c_outer, -self.c_outer)
        path.offset(0, self.c_outer * 2 - bold)
        path.offset(-self.c_outer, -self.c_outer)
        path.offset(self.c_outer - self.ra + self.r_hole, 0)
        path.offset(0, bold)
        path.offset(self.ra - self.c_outer - self.r_hole, 0)
        drawer.switch_layer(LayerType.SOLID)
        objs = [path.draw(drawer)]
        objs.append(drawer.line(
            (self.rf, self.half_bold),
            (self.rf, -self.half_bold)
        ))
        drawer.switch_layer(LayerType.DOTTED)
        axis = drawer.line(
            (self.r, self.half_bold + 3),
            (self.r, -self.half_bold - 3)
        )

        drawer.switch_layer(LayerType.THIN)
        if self.rotation == GearRotation.NONE or is_second:
            aux_rect = drawer.rect(
                (self.r_hole, self.half_bold),
                (self.rf, -self.half_bold)
            )
            hatch = drawer.hatch(aux_rect)
            aux_rect.Delete()
        else:
            width = (self.ra - self.r_hole) / 4
            pt1 = (self.rf - width, self.half_bold)
            pt2 = (self.rf - width, -self.half_bold)
            spl = drawer.random_spline(pt1, pt2)
            aux_pts = [pt1, (self.r_hole, self.half_bold),
                       (self.r_hole, -self.half_bold), pt2]
            aux_polyline = drawer.polyline(aux_pts)
            hatch = drawer.hatch([spl, aux_polyline])
            a1, a2 = width * 1 / 6, width * 1 / 6
            xc = self.rf - width / 2
            match self.rotation:
                case GearRotation.COUTER_CLOCKWISE:
                    objs.append(drawer.line(
                        (xc + a1 / 2 + a2, -self.half_bold),
                        (xc + a1 / 2 - a2, self.half_bold)))
                    objs.append(drawer.line(
                        (xc - a1 / 2 + a2, -self.half_bold),
                        (xc - a1 / 2 - a2, self.half_bold)))
                case GearRotation.CLOCKWISE:
                    objs.append(drawer.line(
                        (xc + a1 / 2 + a2, self.half_bold),
                        (xc + a1 / 2 - a2, -self.half_bold)))
                    objs.append(drawer.line(
                        (xc - a1 / 2 + a2, self.half_bold),
                        (xc - a1 / 2 - a2, -self.half_bold)))

        return objs, hatch, axis

    def draw(self, drawer: Drawer,
             center_pos: ndarray,
             dir_vec: ndarray):
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)

        # get rotation angle from vector
        theta = np.arctan2(dir_vec[1], dir_vec[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            res = DrawedGear()

            wipe = Path2D((-self.ra + 1, -self.half_bold))
            wipe.offset(self.ra * 2 - self.c_outer * 2, 0)
            wipe.offset(self.c_outer, self.c_outer)
            wipe.offset(0, self.half_bold * 2 - self.c_outer * 2)
            wipe.offset(-self.c_outer, self.c_outer)
            wipe.offset(-self.ra * 2 + self.c_outer * 2, 0)
            wipe.offset(-self.c_outer, -self.c_outer)
            wipe.offset(0, -self.half_bold * 2 + self.c_outer * 2)
            wipe.offset(self.c_outer, -self.c_outer)
            drawer.switch_layer(LayerType.SOLID)
            res.wipeout = wipe.wipeout(drawer)

            res.right, res.right_hatch, res.right_axis = self._draw_half(
                drawer, False)

            with drawer.transformed(mirrored_axis='y'):
                res.left, res.left_hatch, res.left_axis = self._draw_half(
                    drawer, True)

            return res


class KeywayType(Enum):
    A = 'A'  # 半圆键
    B = 'B'  # 方键
    C = 'C'  # 单半圆键


class Keyway:
    SIZE_LOOKUP_TABLE = [
        (6, 8), (8, 10), (10, 12), (12, 17),
        (17, 22), (22, 30), (30, 38), (38, 44),
        (44, 50), (50, 58), (58, 65), (65, 75),
        (75, 85), (85, 95), (95, 110), (110, 130),
        (130, 150), (150, 170), (170, 200),
        (200, 230), (230, 260), (260, 290),
        (290, 330), (330, 380), (380, 440), (440, 500)
    ]
    BOLD_TABLE = [2, 3, 4, 5, 6, 8, 10, 12, 14, 16,
                  18, 20, 22, 25, 28, 32, 36, 40, 45,
                  50, 56, 63, 70, 80, 90, 100]  # H8 配合
    ALL_LENGTH = [6, 8, 10, 12, 14, 16, 18, 20, 22,
                  25, 28, 32, 36, 40, 45, 50, 56, 63,
                  70, 80, 90, 100, 110, 125, 140, 160,
                  180, 200, 220, 250, 280, 320, 360,
                  400, 450, 500]
    LENGTH_LOOKUP_RANGE = [
        (0, 8), (0, 13), (1, 15), (2, 17), (4, 19), (6, 21),
        (8, 23), (10, 25), (12, 26), (14, 27), (15, 28),
        (16, 29), (17, 30), (18, 31), (19, 32), (20, 33),
        (20, 34), (21, 34), (22, 35), (23, 36), (24, 36),
        (25, 36), (26, 36), (27, 36), (28, 36)
    ]
    HEIGHT_TABLE = [2, 3, 4, 5, 6, 7, 8, 8, 9, 10,
                    11, 12, 14, 14, 16, 18, 20, 22,
                    25, 28, 32, 32, 36, 40, 45, 50]  # H11 或 H8 配合
    T_SHAFT_TABLE = [
        1.2, 1.8, 2.5, 3.0, 3.5, 4.0, 5.0, 5.0, 5.5, 6.0, 7.0, 7.5, 9.0, 9.0, 10.0,
        11.0, 12.0, 13.0, 15.0, 17.0, 20.0, 20.0, 22.0, 25.0, 28.0, 31.0
    ]
    T_HUB_TABLE = [
        1.0, 1.4, 1.8, 2.3, 2.8, 3.3, 3.3, 3.3, 3.8, 4.3, 4.4, 4.9, 5.4, 5.4, 6.4,
        7.4, 8.4, 9.4, 10.4, 11.4, 12.4, 12.4, 14.4, 15.4, 17.4, 19.5
    ]

    def __init__(self, length, diameter, ktype=KeywayType.A):
        self.length = length
        self.r = diameter / 2

        if length > diameter * 1.6:
            raise ValueError("长度超过了给定直径的最大允许长度。")

        for idx, (min_d, max_d) in enumerate(Keyway.SIZE_LOOKUP_TABLE):
            if min_d <= diameter < max_d:
                self.width = Keyway.BOLD_TABLE[idx]
                self.height = Keyway.HEIGHT_TABLE[idx]
                self.t_shaft = Keyway.T_SHAFT_TABLE[idx]
                self.t_hub = Keyway.T_HUB_TABLE[idx]
                start, end = Keyway.LENGTH_LOOKUP_RANGE[idx]
                valid_lengths = Keyway.ALL_LENGTH[start:end]
                if length not in valid_lengths:
                    raise ValueError(f"长度 {length} 不在有效范围 {valid_lengths} 内。")
                break
        else:
            raise ValueError(f"直径 {diameter} 超出了键槽尺寸查找的范围。")

        self.type = ktype
        self.left_top = (-self.width / 2, self.length / 2)
        self.right_bottom = (self.width / 2, -self.length / 2)

    def _draw_on_shaft(self, drawer: Drawer):
        drawer.switch_layer(LayerType.SOLID)
        drawer.wipeout_rect(self.left_top, self.right_bottom)

        match self.type:
            case KeywayType.A:
                y_off = (self.length - self.width) / 2
                arc1 = drawer.arc((0, y_off), self.width / 2,
                                  0, 180)
                arc2 = drawer.arc((0, -y_off), self.width / 2,
                                  180, 360)
                line1 = drawer.line((self.width / 2, y_off),
                                    (self.width / 2, -y_off))
                line2 = drawer.line((-self.width / 2, y_off),
                                    (-self.width / 2, -y_off))
                return [arc1, arc2, line1, line2]
            case KeywayType.B:
                rect = drawer.rect(self.left_top, self.right_bottom)
                return [rect]
            case KeywayType.C:
                arc1 = drawer.arc((0, (self.length - self.width) / 2),
                                  self.width / 2, 0, 180)
                path = Path2D(
                    (-self.width / 2, (self.length - self.width) / 2))
                path.offset(0, -self.length + self.width / 2)
                path.offset(self.width, 0)
                path.offset(0, self.length - self.width / 2)
                return [arc1, path.draw(drawer)]

    def _draw_on_hub(self, drawer: Drawer, hub_bold: float):
        drawer.switch_layer(LayerType.SOLID)

        lt = (self.r, hub_bold / 2)
        rb = (self.r + self.t_hub, -hub_bold / 2)
        drawer.wipeout_rect(lt, rb)
        return drawer.rect(lt, rb)

    def draw(self, drawer: Drawer,
             center_pos: ndarray,
             direction: ndarray,
             hub_bold: float):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            result = (
                self._draw_on_shaft(drawer),
                self._draw_on_hub(drawer, hub_bold),
            )
            return result


@dataclass
class DrawedBushing:
    rects: list[CDispatch] = None
    hatchs: list[CDispatch] = None
    wipeouts: list[CDispatch] = None


class Bushing:
    def __init__(self, d1, d2, length):
        self.d1 = d1
        self.d2 = d2
        self.length = length

    def draw(self, drawer: Drawer,
             center_pos: ndarray,
             direction: ndarray):
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)

        res = DrawedBushing([], [], [])
        drawer.switch_layer(LayerType.SOLID)
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            lt = np.array((-self.length / 2, self.d1 / 2))
            rb = np.array((self.length / 2, self.d2 / 2))
            res.wipeouts.append(drawer.wipeout_rect(lt, rb))
            res.rects.append(drawer.rect(lt, rb))
            res.hatchs.append(drawer.hatch(res.rects[0]))
            lt, rb = -lt, -rb
            res.wipeouts.append(drawer.wipeout_rect(lt, rb))
            res.rects.append(drawer.rect(lt, rb))
            res.hatchs.append(drawer.hatch(res.rects[1]))
            return res


@dataclass
class Fillet:
    radius: float
    center: tuple
    pts: list
    start_angle: float
    stop_angle: float


@dataclass
class _StepFeature:
    position: float
    size: float
    is_abs: bool

    def __iter__(self):
        return iter((self.position, self.size, self.is_abs))


@dataclass
class _ShoulderFeature:
    position: float
    width: float


@dataclass
class _BushingFeature:
    position: float
    height: float
    width: float


@dataclass
class _GearFeature:
    position: float
    gear: Gear


@dataclass
class _BearingFeature:
    position: float
    bearing: Bearing


class PutSide(Enum):
    AFTER = 'after'
    BEFORE = 'before'


def _get_offset(feat, halfl, put_side):
    if isinstance(feat, _StepFeature):
        offset = -halfl
        if put_side == PutSide.AFTER:
            offset = -offset
    elif isinstance(feat, _ShoulderFeature):
        offset = -halfl
        if put_side == PutSide.AFTER:
            offset = -offset + feat.width
    else:
        # 确定特征宽度
        if isinstance(feat, _BushingFeature):
            feature_width = feat.width / 2
        elif isinstance(feat, _GearFeature):
            feature_width = feat.gear.half_bold
        elif isinstance(feat, _BearingFeature):
            feature_width = feat.bearing.b / 2
        else:
            raise ValueError("不支持的特征类型。")

        # 计算偏移量
        if put_side == PutSide.BEFORE:
            offset = -halfl - feature_width
        else:
            offset = halfl + feature_width
    return offset


class Shaft:
    CR_TABLE = {
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

    @staticmethod
    def _get_chamfer_radius(diameter):
        for k, v in Shaft.CR_TABLE.items():
            if k[0] < diameter <= k[1]:
                return v
        warnings.warn(f"直径 {diameter} 超出了倒角半径计算的范围。", BadDesignWarning)

    def __init__(self, init_diam):
        self.initial_diameter = init_diam
        self.length = None
        self.steps: list[_StepFeature] = []

        self.contour = []            # 原始轮廓
        self.chamfered_contour = []  # 倒角处理后的轮廓
        self.chamfer_mode = {
            'fillet': None,
            'chamfer': None
        }
        self.need_refresh = True

        self.gears: list[tuple[float, Gear, bool]] = []
        self.keyways: list[tuple[float, Keyway, float, bool]] = []
        self.bearings: list[tuple[float, Bearing, bool]] = []
        self.bushings: list[tuple[float, Bushing]] = []

    def add_step(self, position, height=None, diameter=None):
        if height is not None:
            feat = _StepFeature(position, height, False)
        elif diameter is not None:
            feat = _StepFeature(position, diameter, True)
        else:
            raise ValueError("必须提供高度或直径。")
        self.need_refresh = True  # 需要重新计算轮廓
        self.steps.append(feat)
        return feat

    def add_shoulder(self, position, height, width):
        if width < height * 1.4:
            warnings.warn(f"{position} 处的肩部过窄，一般应大于高度的 1.4 倍。",
                          BadDesignWarning)
        d = self._get_diameter_at(position, False)
        if not 0.07 * d <= height <= 0.1 * d:
            warnings.warn(
                f"{position} 处的肩部高度 {height} 不在推荐范围 ({0.07 * d}, {0.1 * d}) 内。",
                BadDesignWarning)

        self.need_refresh = True  # 需要重新计算轮廓
        self.steps.append(_StepFeature(position, height, False))
        self.steps.append(_StepFeature(position + width, -height, False))
        return _ShoulderFeature(position, width)

    def add_bushing(self, feat, height, width, put_side=PutSide.BEFORE):
        offset = _get_offset(feat, width / 2, put_side)
        pos = feat.position + offset
        d1 = self._get_diameter_at(pos, False)
        self.bushings.append((pos, Bushing(d1, d1 + height * 2, width)))
        return _BushingFeature(pos, height, width)

    def add_keyway(self, feat, length, forward=True):
        if isinstance(feat, (_GearFeature,)):
            pos = feat.position
            bold = feat.gear.half_bold * 2
        else:
            raise ValueError("不支持的特征类型。")
        self.keyways.append((pos, Keyway(
            length, self._get_diameter_at(pos, False)
        ), bold, forward))

    def add_gear(self, pos_or_feat, gear: Gear,
                 forward=True, put_side=PutSide.BEFORE):
        if not isinstance(pos_or_feat, float):
            pos_or_feat = pos_or_feat.position + _get_offset(
                pos_or_feat, gear.half_bold, put_side)

        self.gears.append((pos_or_feat, gear, forward))
        return _GearFeature(pos_or_feat, gear)

    def add_bearing(self, feat, bearing: Bearing,
                    forward=True, put_side=PutSide.BEFORE):
        if not isinstance(feat, _BushingFeature):
            raise NotImplementedError(f"不支持的特征类型: {type(feat)}")
        bearing.check_attach(feat.height)
        pos = feat.position + _get_offset(
            feat, bearing.b / 2, put_side)
        self.bearings.append((pos, bearing, forward))
        return _BearingFeature(pos, bearing)

    def _get_diameter_at(self, pos, check_length=True,
                         put_side=PutSide.BEFORE):
        self.process_features(False, False)
        if check_length and (pos < 0 or pos > self.length):
            raise ValueError(f"位置 {pos} 超出了轴的长度范围。")
        if put_side == PutSide.BEFORE:
            def _check(x0, p, x1):
                return x0 <= p < x1
        else:
            def _check(x0, p, x1):
                return x0 < p <= x1
        for i in range(len(self.contour) - 1):
            x0, d0 = self.contour[i]
            x1, _ = self.contour[i + 1]
            if _check(x0, pos, x1):
                return d0
        return self.contour[-1][1]

    def process_features(self, do_fillet=False, do_chamfer=True, num_pt_per_arc=5):
        if not (self.need_refresh) and (
            self.chamfer_mode['fillet'] == do_fillet and
            self.chamfer_mode['chamfer'] == do_chamfer
        ):
            return

        # 检查所有零件是否定位良好
        step_pos = tuple(map(lambda x: x.position, self.steps)) +\
            sum(((pos - bu.length / 2, pos + bu.length / 2)
                 for pos, bu in self.bushings), ())
        for pos, g, _ in self.gears:
            if not (
                pos + g.half_bold in step_pos or
                pos - g.half_bold in step_pos
            ):
                print(f'({pos - g.half_bold} - {pos + g.half_bold})')
                warnings.warn(f"位于 {pos} 的齿轮可能没有良好定位", BadDesignWarning)
        for pos, b, _ in self.bearings:
            if not (
                pos + b.b / 2 in step_pos or
                pos - b.b / 2 in step_pos
            ):
                print(f'({pos - b.b / 2} - {pos + b.b / 2})')
                warnings.warn(f"位于 {pos} 的轴承可能没有良好定位", BadDesignWarning)

        events = []
        events.append((0, self.initial_diameter))

        # 处理阶梯特征
        current_diam = self.initial_diameter
        self.steps.sort(key=lambda x: x.position)
        for pos, l, absolute in self.steps:
            if absolute:
                current_diam = l
            else:
                current_diam += l
            events.append((pos, current_diam))

        # 生成基础轮廓
        self.contour = []
        current_diam = self.initial_diameter
        self.contour.append((0, current_diam))
        for pos, diam in events:
            if diam != current_diam:
                self.contour.extend([(pos, current_diam), (pos, diam)])
            else:
                self.contour.append((pos, diam))
            current_diam = diam

        # 合并相同点
        merged_contour = []
        for i, c in enumerate(self.contour):
            if i == 0 or c != merged_contour[-1]:
                merged_contour.append(c)
        self.contour = merged_contour

        if do_chamfer:
            self.length = self.contour[-1][0]
            pos, d = self.contour[0]
            self.contour[0] = (pos + 1, d)
            self.contour.insert(0, (pos, d - 2))
            pos, d = self.contour[-1]
            self.contour[-1] = (pos - 1, d)
            self.contour.append((pos, d - 2))
        self.chamfer_mode['chamfer'] = do_chamfer

        # 倒角处理
        if do_fillet:
            self._apply_chamfers(num_pt_per_arc)
        else:
            self.chamfered_contour = [(x, y / 2) for x, y in self.contour]
        self.chamfer_mode['fillet'] = do_fillet

    def _apply_chamfers(self, num_pt_per_arc):
        self.chamfered_contour = []

        i = 0
        while i < len(self.contour) - 1:
            x0, d0 = self.contour[i]
            x1, d1 = self.contour[i+1]

            if x0 == x1 and d0 != d1:  # 垂直段（直径变化点）
                # 转换为半径单位进行计算
                r0, r1 = d0 / 2, d1 / 2
                delta_r = r1 - r0
                fradius = Shaft._get_chamfer_radius(min(r0, r1))

                # 内侧
                cx = x0 - np.sign(delta_r) * fradius
                cy = min(r0, r1) + fradius
                if delta_r > 0:
                    start_angle = -np.pi / 2
                    stop_angle = 0
                else:
                    start_angle = -np.pi
                    stop_angle = -np.pi / 2

                # 生成内圆角坐标（直径单位）
                theta = np.linspace(start_angle, stop_angle, num_pt_per_arc)
                pts = zip(cx + fradius * np.cos(theta),
                          cy + fradius * np.sin(theta))

                # 合并并排序坐标点
                if delta_r > 0:
                    self.chamfered_contour.append((cx, d0 / 2))
                else:
                    self.chamfered_contour.append((x0, d0 / 2))
                    self.chamfered_contour.append((x0, cy))
                self.chamfered_contour.append(Fillet(
                    fradius, (cx, cy), list(pts),
                    start_angle, stop_angle,
                ))
                if delta_r > 0:
                    self.chamfered_contour.append((x1, cy))
                    self.chamfered_contour.append((x1, d1 / 2))
                else:
                    self.chamfered_contour.append((cx, d1 / 2))
                i += 1
            else:  # 水平段
                self.chamfered_contour.append((x0, d0 / 2))
            i += 1

        # 添加轮廓末端
        last = self.contour[-1]
        self.chamfered_contour.append((last[0], last[1] / 2))

    def _draw_half_contour(self, drawer: Drawer):
        drawer.switch_layer(LayerType.SOLID)
        path = Path2D((0, 0))
        for segment in self.chamfered_contour:
            if isinstance(segment, Fillet):
                path.draw(drawer)
                path = None
                drawer.arc(segment.center, segment.radius,
                           np.degrees(segment.start_angle),
                           np.degrees(segment.stop_angle))
            else:
                if path is None:
                    path = Path2D(segment)
                else:
                    path.goto(segment)
        path.goto(self.length, 0)
        path.draw(drawer)

    def draw(self, drawer: Drawer,
             top_center: ndarray,
             direction: ndarray,
             do_fillet=False):
        self.process_features(do_fillet)

        if not isinstance(direction, ndarray):
            direction = np.array(direction)
        if not isinstance(top_center, ndarray):
            top_center = np.array(top_center)

        drawer.switch_layer(LayerType.SOLID)
        theta = np.arctan2(direction[1], direction[0]) - np.pi

        with drawer.transformed(top_center, theta):
            for pos, bearing, forward in self.bearings:
                bearing.draw(
                    drawer, (pos, 0),
                    (-1, 0) if forward else (1, 0))

            for pos, gear, forward in self.gears:
                gear.draw(
                    drawer, (pos, 0),
                    (-1, 0) if forward else (1, 0))

            # WIPEOUT
            pts_list = map(lambda x: x.pts if isinstance(x, Fillet)
                           else [x], self.chamfered_contour)
            pts_list = sum(pts_list, start=[])
            pts = pts_list + [(pt[0], -pt[1]) for pt in reversed(pts_list)]
            drawer.wipeout(*pts)

            # Contour
            self._draw_half_contour(drawer)
            with drawer.transformed(mirrored_axis='x'):
                self._draw_half_contour(drawer)

            for pos, bushing in self.bushings:
                bushing.draw(
                    drawer, (pos, 0), (0, 1))

            for pos, keyway, bold, forward in self.keyways:
                keyway.draw(
                    drawer, (pos, 0),
                    (-1, 0) if forward else (1, 0), bold)
