from enum import Enum
import math
import re
from dataclasses import dataclass

import numpy as np
from numpy import ndarray
from win32com.client import CDispatch
import pandas as pd

from drawer import (
    Drawer, Path2D, LayerType
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

        # get rotation angle from vector
        theta = np.arctan2(dir_vec[1], dir_vec[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            res = DrawedGear()

            wipe = Path2D((-self.ra + 1, -self.half_bold))
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
            raise ValueError(
                "Length exceeds the maximum allowable length for the given diameter.")

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

    def _draw_on_hub(self, drawer: Drawer):
        drawer.switch_layer(LayerType.SOLID)

        lt = (self.r, self.length / 2)
        rb = (self.r + self.t_hub, -self.length / 2)
        drawer.wipeout_rect(lt, rb)
        return drawer.rect(lt, rb)

    def draw(self, drawer: Drawer,
             center_pos: ndarray,
             direction: ndarray):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            result = (
                self._draw_on_shaft(drawer),
                self._draw_on_hub(drawer),
            )
            return result


@dataclass
class Fillet:
    radius: float
    center: tuple
    pts: list
    start_angle: float
    stop_angle: float


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
        self.length = None
        self.steps = []          # [(位置, 值, 是否绝对直径)]

        self.contour = []            # 原始轮廓
        self.chamfered_contour = []  # 倒角处理后的轮廓

        self.gears: list[tuple[float, Gear]] = []
        self.keyways: list[tuple[float, Keyway]] = []
        self.bearings: list[tuple[float, Bearing]] = []

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
        self.steps.append((position, height, False))
        self.steps.append((position + width, -height, False))

    def add_keyway(self, position, keyway: Keyway):
        self.keyways.append((position, keyway))

    def add_gear(self, pos, gear: Gear):
        self.gears.append((pos, gear))

    def process_features(self, num_pt_per_arc=5):
        events = []
        events.append((0, self.initial_diameter))

        # 处理阶梯特征
        current_diam = self.initial_diameter
        self.steps.sort(key=lambda x: x[0])
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

        self.length = self.contour[-1][0]
        pos, d = self.contour[0]
        self.contour[0] = (pos + 1, d)
        self.contour.insert(0, (pos, d - 2))
        pos, d = self.contour[-1]
        self.contour[-1] = (pos - 1, d)
        self.contour.append((pos, d - 2))
        print(self.contour)

        # 倒角处理
        self._apply_chamfers(num_pt_per_arc)

    def _apply_chamfers(self, num_pt_per_arc):
        self.chamfered_contour = []

        for i in range(len(self.contour)-1):
            x0, d0 = self.contour[i]
            x1, d1 = self.contour[i+1]

            if x0 == x1 and d0 != d1:  # 垂直段（直径变化点）
                # 转换为半径单位进行计算
                r0, r1 = d0 / 2, d1 / 2
                delta_r = r1 - r0
                fradius = self._get_chamfer_radius(min(r0, r1))

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
                    self.contour[i + 1] = (x1, d1)
                else:
                    self.contour[i + 1] = (cx, d1)

            else:  # 水平段
                self.chamfered_contour.append((x0, d0 / 2))

        # 添加轮廓末端
        last = self.contour[-1]
        self.chamfered_contour.append((last[0], last[1] / 2))

    def _draw_half_contour(self, drawer: Drawer):
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
             center: ndarray,
             direction: ndarray):
        if not self.chamfered_contour:
            self.process_features()

        drawer.switch_layer(LayerType.SOLID)
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center, theta):
            # WIPEOUT
            pts_list = map(lambda x: x.pts if isinstance(x, Fillet)
                           else [x], self.chamfered_contour)
            pts_list = sum(pts_list, start=[])
            pts = pts_list + [(pt[0], -pt[1]) for pt in reversed(pts_list)]
            drawer.wipeout(*pts)

            for pos, bearing in self.bearings:
                bearing.draw(drawer, direction, (pos, 0))

            for pos, gear in self.gears:
                gear.draw(drawer, direction, (pos, 0))

            self._draw_half_contour(drawer)
            with drawer.transformed(mirrored_axis='x'):
                self._draw_half_contour(drawer)

            for pos, keyway in self.keyways:
                keyway.draw(
                    drawer, (pos, 0), direction)
