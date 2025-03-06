from enum import Enum
import math
import re
import pandas as pd
from dataclasses import dataclass

import numpy as np
import matplotlib.pyplot as plt
from numpy import ndarray
from matplotlib.patches import Arc, Rectangle
from win32com.client import CDispatch

from drawer import (
    Drawer, Path2D, LayerType,
    get_mirrormat, get_rotmat
)


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
        Draws the inner part of the bearing.

        Params:
            drawer (Drawer): The drawing tool or context to use for rendering the part.
            left_down (ndarray): The (x, y) coordinates for the left down point of the border.
            transform (ndarray): Transform matrix.

        Returns:
            objs (list[Dispatch]): List of drawn objects.
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
                   center_pos: ndarray,
                   transform: ndarray):
        mirror_mat = get_mirrormat('y')

        # 画右边的部分
        drawer.set_transform(tr=transform)
        pos = center_pos + np.array((self.d / 2, -self.b / 2))
        rb = self._draw_border(drawer, pos)
        ri, ht = self._draw_inner(drawer, pos,
                                  False, rb)

        # 画左边的部分
        transform = mirror_mat @ transform
        drawer.set_transform(tr=transform)
        lb = self._draw_border(drawer, pos)
        li = self._draw_inner(drawer, pos, True)

        return rb, ri, ht, lb, li

    def draw(self, drawer: Drawer,
             direction: ndarray,
             center_pos: ndarray):
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
        if not isinstance(direction, ndarray):
            direction = np.array(direction, dtype=np.floating)

        # get rotation angle from vector
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        transform = get_rotmat(center_pos, theta)

        res = DrawedBearing()

        drawer.set_transform(tr=transform)
        wipe_region = Path2D(center_pos - (self.da / 2 - self.c, self.b / 2))
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
        ) = self._draw_side(drawer, center_pos, transform)

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

    def _draw_half(self, drawer: Drawer, is_second=False):
        bold = self.half_bold * 2

        path = Path2D((self.ra - 1, self.half_bold))
        path.offset(1, -1)
        path.offset(0, 2 - bold)
        path.offset(-1, -1)
        path.offset(0, bold)
        path.offset(1 - self.ra + self.r_hole, 0)
        path.offset(0, -bold)
        path.offset(self.ra - 1 - self.r_hole, 0)
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
             dir_vec: ndarray,
             center_pos: ndarray):
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)
        if not isinstance(dir_vec, ndarray):
            dir_vec = np.array(dir_vec, dtype=np.floating)

        # get rotation angle from vector
        theta = np.arctan2(dir_vec[1], dir_vec[0]) - np.pi / 2
        transform = get_rotmat(center_pos, theta)

        res = DrawedGear()

        wipe = Path2D(center_pos - (self.ra - 1, self.half_bold))
        wipe.offset(self.ra * 2 - 2, 0)
        wipe.offset(1, 1)
        wipe.offset(0, self.half_bold * 2 - 2)
        wipe.offset(-1, 1)
        wipe.offset(-self.ra * 2 + 2, 0)
        wipe.offset(-1, -1)
        wipe.offset(0, -self.half_bold * 2 + 2)
        wipe.offset(1, -1)
        drawer.switch_layer(LayerType.SOLID)
        res.wipeout = wipe.wipeout(drawer)

        drawer.set_transform(tr=transform)
        res.right, res.right_hatch, res.right_axis = self._draw_half(
            drawer, False)
        transform = get_mirrormat('y') @ transform
        drawer.set_transform(tr=transform)
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
                  50, 56, 63, 70, 80, 90, 100]
    HEIGHT_TABLE = [2, 3, 4, 5, 6, 7, 8, 8, 9, 10,
                    11, 12, 14, 14, 16, 18, 20, 22,
                    25, 28, 32, 32, 36, 40, 45, 50]
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
            raise ValueError("Length exceeds the maximum allowable length for the given diameter.")
        
        for idx, (min_d, max_d) in enumerate(Keyway.SIZE_LOOKUP_TABLE):
            if min_d <= diameter < max_d:
                self.width = Keyway.BOLD_TABLE[idx]
                self.height = Keyway.HEIGHT_TABLE[idx]
                self.t_shaft = Keyway.T_SHAFT_TABLE[idx]
                self.t_hub = Keyway.T_HUB_TABLE[idx]
                break
        else:
            raise ValueError(
                f"Diameter {diameter} is out of range for keyway size lookup.")

        self.type = ktype
        if ktype in (KeywayType.A, KeywayType.B):
            self.left_top = np.array((-self.width / 2, self.length / 2))
            self.right_bottom = -self.left_top
        elif ktype == KeywayType.C:
            self.left_top = np.array((
                -self.width / 2, (self.length - self.width) / 2))
            self.right_bottom = np.array((self.width / 2, self.length / 2))
        else:
            raise ValueError('不支持的键槽类型')

    def draw_on_shaft(self, drawer: Drawer,
                      center_pos: ndarray,
                      direction: ndarray):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        drawer.set_transform(center_pos, theta)
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

    def draw_on_hub(self, drawer: Drawer,
                    center_pos: ndarray,
                    direction: ndarray):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        drawer.set_transform(center_pos, theta)
        drawer.switch_layer(LayerType.SOLID)
        
        lt = (self.r, self.length / 2)
        rb = (self.r + self.t_hub, -self.length / 2)
        drawer.wipeout_rect(lt, rb)
        return drawer.rect(lt, rb)


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

    def __init__(self, init_diam):
        self.initial_diameter = init_diam
        self.steps = []          # [(位置, 值, 是否绝对直径)]
        self.shoulders = []      # [(位置, 高度, 宽度)]

        self.contour = []            # 原始轮廓
        self.chamfered_contour = []  # 倒角处理后的轮廓

        self.gears = []           # [(位置, Object)]
        self.keyways  = []        # [(位置, Object)]
        self.bearings = []        # [(位置, Object)]

    def _get_chamfer_radius(self, diameter):
        for k, v in Shaft.CR_TABLE.items():
            if k[0] < diameter <= k[1]:
                return v
        raise ValueError(
            f"Diameter {diameter} is out of range for chamfer radius calculation.")

    def add_bearing(self, position, bearing: Bearing):
        self.bearings.append((position, bearing))

    def add_step(self, position, height=None, diameter=None):
        if height is not None:
            self.steps.append((position, height, False))
        elif diameter is not None:
            self.steps.append((position, diameter, True))

    def add_shoulder(self, position, height, width):
        self.shoulders.append((position, height, width))

    def add_keyway(self, position, keyway: Keyway):
        self.keyways.append((position, keyway))

    def add_gear(self, pos, gear: Gear):
        self.gears.append((pos, gear))

    def _get_diameter_at(self, pos, events):
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
