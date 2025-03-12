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
    Drawer, Path2D, LayerType, HatchType
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


class BearingCover:
    BEARING_BASE = {
        'D': [47, 52, 62, 72, 80, 85, 90, 100, 110, 120, 125,
              130, 140, 150, 160, 170, 180, 190, 200],
        'D1': [68, 72, 85, 95, 105, 110, 115, 125, 140, 150,
               155, 160, 170, 185, 195, 205, 215, 225, 235],
        'D2': [85, 90, 105, 115, 125, 130, 135, 145, 165, 175,
               180, 185, 200, 215, 230, 240, 255, 265, 275],
        'd1': [8, 8, 8, 10, 10, 10, 12, 12, 12, 16,
               16, 16, 16, 16, 16, 16, 16, 16, 16],
        'n': [4, 4, 4, 4, 4, 6, 6, 6, 6, 6,
              6, 6, 6, 6, 6, 6, 6, 6, 6]
    }

    def __init__(self, da, dd, m, is_open=False):
        D = da
        if D in self.BEARING_BASE['D']:
            idx = self.BEARING_BASE['D'].index(D)
        else:
            idx = min(self.BEARING_BASE['D'], key=lambda x: abs(x - D))
            idx = self.BEARING_BASE['D'].index(idx)
        self.d3 = self.BEARING_BASE['d1'][idx]  # 轴承盖固定螺栓直径d₄
        self.D0 = self.BEARING_BASE['D1'][idx]  # 轴承盖螺栓分布圆直径D₁
        self.D2 = self.BEARING_BASE['D2'][idx]  # 轴承座凸缘端面直径D₂
        self.n = self.BEARING_BASE['n'][idx]
        self.d0 = self.d3 + 1
        self.D4 = D - 10
        self.e___ = 1.2 * self.d3
        self.e = self.e___ + 1
        self.e1 = self.e___ + 0.2
        self.D = D
        self.m__ = m + 1
        self.m = m

        self.cr = 1
        self.is_open = is_open

        d = [15, 20, 25, 30, 35, 40, 45, 50, 55, 60,
             65, 70, 75, 80, 85, 90, 95, 100, 105, 110]
        D = [29, 33, 39, 45, 49, 53, 61, 69, 74, 80, 84,
             90, 94, 102, 107, 112, 117, 122, 127, 132]
        d1 = [14, 19, 24, 29, 34, 39, 44, 49, 53, 58,
              63, 68, 73, 78, 83, 88, 93, 98, 103, 108]
        B = [6, 6, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 9, 9, 9, 10, 10, 10, 10]
        D0 = [28, 32, 38, 44, 48, 52, 60, 68, 72, 78, 82,
              88, 92, 100, 105, 110, 115, 120, 125, 130]
        d0 = [16, 21, 26, 31, 36, 41, 46, 51, 56, 61,
              66, 71, 77, 82, 87, 92, 97, 102, 107, 112]
        b = [5, 5, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8]
        delta = [10, 10, 12, 12, 12, 12, 12, 12, 12,
                 12, 12, 12, 12, 15, 15, 15, 15, 15, 15, 15]
        idx = min(d, key=lambda x: abs(x - dd))
        idx = d.index(idx)
        delta = delta[idx]
        self.b = b[idx] * 1.5
        self.b0 = b[idx]
        self.yoff = (delta - self.b) / 2
        self.yoff2 = (self.b - self.b0) / 2
        self.b1 = self.cr + self.yoff * 3 + self.yoff2 * 4 + self.b0 * 2
        self.D1 = D0[idx]
        self.d1 = d0[idx]

        self.d = dd
        self.B = (self.D1 - dd) / (
            self.D1 - self.d1) * (self.b - self.b0) + self.b0
        self.yoff1 = self.yoff - (self.B - self.b)
        self.yoff3 = (self.yoff - self.yoff1) / 2 + self.yoff2
        self.ccc = self.yoff1 + (self.yoff - self.yoff1) / 2
        
    def _draw_close(self, drawer: Drawer):
        drawer.switch_layer(LayerType.SOLID)
        e = self.e___
        with drawer.transformed((0, 1)):
            path = Path2D((0, e))
            path.goto(-self.D2 / 2 + self.cr, e)
            path.offset(-self.cr, -self.cr)
            path.offset(0, -e + self.cr)
            path.goto(-self.D / 2 + self.cr, 0)
            path.offset(0, -self.cr)
            path.offset(-self.cr, 0)
            path.offset(0, -self.e1 + self.cr)
            path.goto(-self.D / 2, -self.e1)
            path.offset(self.cr, 0)
            path.offset(0, -self.m__ + self.e1)
            path.offset((self.D - self.D4) / 2 - self.cr, 0)
            path.goto(-self.D4 / 2 + 2, e - self.b1)
            path.goto(0, e - self.b1)
            drawer.switch_layer(LayerType.SOLID)
            path.wipeout(drawer)
            left = path.draw(drawer)
            with drawer.transformed(mirrored_axis='y'):
                path.wipeout(drawer)
                right = path.draw(drawer)
            drawer.switch_layer(LayerType.THIN)
            drawer.hatch([left[0], right[0]])
            
            drawer.switch_layer(LayerType.SOLID)
            drawer.hatch(drawer.rect(
                (-self.D2 / 2, 0),
                (-self.D / 2 + 1, -1)
            ), hatch_type=HatchType.SOLID)
            with drawer.transformed(mirrored_axis='y'):
                drawer.hatch(drawer.rect(
                    (-self.D2 / 2, 0),
                    (-self.D / 2 + 1, -1)
                ), hatch_type=HatchType.SOLID)

    def _draw_open(self, drawer: Drawer):
        drawer.switch_layer(LayerType.SOLID)
        e__ = self.e___
        with drawer.transformed((0, 1)):
            path = Path2D((-self.D0 / 2 + self.d0 * 1.5, e__))
            path.goto(-self.D2 / 2 + self.cr, e__)
            path.offset(-self.cr, -self.cr)
            path.offset(0, -e__ + self.cr)
            path.goto(-self.D / 2 + self.cr, 0)
            path.offset(0, -self.cr)
            path.offset(-self.cr, 0)
            path.offset(0, -self.e1 + self.cr)
            path.goto(-self.D / 2, -self.e1)
            path.offset(self.cr, 0)
            path.offset(0, -self.m__ + self.e1)
            path.offset((self.D - self.D4) / 2 - self.cr, 0)
            path.goto(-self.D4 / 2 + 2, e__ - self.b1)
            path.goto(-self.d1 / 2, e__ - self.b1)
            path.offset(0, self.yoff)
            path.offset((self.d1 - self.D1) / 2, self.yoff2)
            path.offset(0, self.b0)
            path.offset((self.D1 - self.d1) / 2, self.yoff2)
            path.offset(0, self.yoff)
            path.offset((self.d1 - self.D1) / 2, self.yoff2)
            path.offset(0, self.b0)
            path.offset((self.D1 - self.d1) / 2, self.yoff2)
            path.offset(0, self.yoff)
            path.goto(-self.D0 / 2 + self.d0 * 1.5, e__ - self.cr)
            path.offset(0, self.cr)
            drawer.switch_layer(LayerType.SOLID)
            path.wipeout(drawer)
            left = path.draw(drawer)
            drawer.switch_layer(LayerType.THIN)
            drawer.hatch(left)
            with drawer.transformed(mirrored_axis='y'):
                drawer.switch_layer(LayerType.SOLID)
                path.wipeout(drawer)
                right = path.draw(drawer)
                drawer.switch_layer(LayerType.THIN)
                drawer.hatch(right)
            path = Path2D((-self.d / 2, e__ - self.b1 + self.ccc))
            path.offset((self.d - self.D1) / 2, self.yoff3)
            path.offset(0, self.b0)
            path.offset((self.D1 - self.d) / 2, self.yoff3)
            path.offset(0, self.yoff1)
            path.offset((self.d - self.D1) / 2, self.yoff3)
            path.offset(0, self.b0)
            path.offset((self.D1 - self.d) / 2, self.yoff3)
            path.goto((-self.d / 2, e__ - self.b1 + self.ccc))
            maozan = path.wipeout(drawer)
            drawer.switch_layer(LayerType.SOLID)
            maozan = path.draw(drawer)
            drawer.hatch(maozan, hatch_type=HatchType.RUBBER)
            drawer.line((-self.D0 / 2 + self.d0 * 1.5, e__),
                        (-self.d / 2, e__))
            drawer.line((-self.D0 / 2 + self.d0 * 1.5, e__ - self.cr),
                        (-self.d / 2, e__ - self.cr))
            drawer.line((-self.d1 / 2, e__ - self.b1),
                        (-self.d / 2, e__ - self.b1))
            with drawer.transformed(mirrored_axis='y'):
                drawer.line((-self.D0 / 2 + self.d0 * 1.5, e__),
                            (-self.d / 2, e__))
                drawer.line((-self.D0 / 2 + self.d0 * 1.5, e__ - self.cr),
                            (-self.d / 2, e__ - self.cr))
                drawer.line((-self.d1 / 2, e__ - self.b1),
                            (-self.d / 2, e__ - self.b1))
                maozan = path.wipeout(drawer)
                drawer.switch_layer(LayerType.SOLID)
                maozan = path.draw(drawer)
                drawer.hatch(maozan, hatch_type=HatchType.RUBBER)

            drawer.hatch(drawer.rect(
                (-self.D2 / 2, 0),
                (-self.D / 2 + 1, -1)
            ), hatch_type=HatchType.SOLID)
            with drawer.transformed(mirrored_axis='y'):
                drawer.hatch(drawer.rect(
                    (-self.D2 / 2, 0),
                    (-self.D / 2 + 1, -1)
                ), hatch_type=HatchType.SOLID)

            # with drawer.transformed((-self.D0 / 2, 0)):
            #     lt = (-self.d0 / 2, e__)
            #     rb = (self.d0 / 2, 0)
            #     drawer.wipeout_rect(lt, rb)
            #     drawer.rect(lt, rb)
            #     drawer.switch_layer(LayerType.DOTTED)
            #     drawer.line((0, -3), (0, e__ + 3))
            # drawer.switch_layer(LayerType.SOLID)
            # with drawer.transformed((self.D0 / 2, 0)):
            #     lt = (-self.d0 / 2, e__)
            #     rb = (self.d0 / 2, 0)
            #     drawer.wipeout_rect(lt, rb)
            #     drawer.rect(lt, rb)
            #     drawer.switch_layer(LayerType.DOTTED)
            #     drawer.line((0, -3), (0, e__ + 3))

    def draw(self, drawer: Drawer,
             center, direction):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        drawer.switch_layer(LayerType.SOLID)

        with drawer.transformed(center, theta):
            if self.is_open:
                self._draw_open(drawer)
            else:
                self._draw_close(drawer)

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
        teeth_v = teeth / (beta.cos())
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
        self.c_inner = Shaft._get_chamfer_radius(None, self.r_hole)

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
             hub_bold: float, on_hub=False):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            if on_hub:
                result = (
                    self._draw_on_shaft(drawer),
                    self._draw_on_hub(drawer, hub_bold),
                )
            else:
                result = self._draw_on_shaft(drawer)
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

        self.rise = None

    def draw(self, drawer: Drawer,
             center_pos: ndarray,
             direction: ndarray):
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)

        res = DrawedBushing([], [], [])
        drawer.switch_layer(LayerType.SOLID)
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        if self.rise is None:
            with drawer.transformed(center_pos, theta):
                lt = np.array((-self.length / 2, self.d1 / 2))
                rb = np.array((self.length / 2, self.d2 / 2))
                res.wipeouts.append(drawer.wipeout_rect(lt, rb))
                res.rects.append(drawer.rect(lt, rb))
                drawer.switch_layer(LayerType.THIN)
                res.hatchs.append(drawer.hatch(res.rects[0]))
                drawer.switch_layer(LayerType.SOLID)
                lt, rb = -lt, -rb
                res.wipeouts.append(drawer.wipeout_rect(lt, rb))
                res.rects.append(drawer.rect(lt, rb))
                drawer.switch_layer(LayerType.THIN)
                res.hatchs.append(drawer.hatch(res.rects[1]))
                return res
        with drawer.transformed(center_pos, theta):
            rpos, rd, rl = self.rise
            path = Path2D((self.length / 2, self.d1 / 2))
            path.offset(-self.length, 0)
            path.offset(0, (self.d2 - self.d1) / 2)
            path.offset(rpos, 0)
            path.offset(0, (rd - self.d2) / 2)
            path.offset(rl, 0)
            path.offset(0, -(rd - self.d2) / 2)
            path.goto(self.length / 2, self.d2 / 2)
            path.goto(self.length / 2, self.d1 / 2)
            res.wipeouts.append(path.wipeout(drawer))
            res.rects.append(path.draw(drawer))
            drawer.switch_layer(LayerType.THIN)
            res.hatchs.append(drawer.hatch(res.rects[0]))
            drawer.switch_layer(LayerType.SOLID)
            with drawer.transformed(mirrored_axis='x'):
                res.wipeouts.append(path.wipeout(drawer))
                res.rects.append(path.draw(drawer))
                drawer.switch_layer(LayerType.THIN)
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
class _FixedFeature:
    position: float


@dataclass
class _StartFeature(_FixedFeature):
    pass


@dataclass
class _EndFeature(_FixedFeature):
    pass


@dataclass
class _CouplingFeature(_FixedFeature):
    length: float


@dataclass
class _StepFeature(_FixedFeature):
    size: float
    is_abs: bool

    def __iter__(self):
        return iter((self.position, self.size, self.is_abs))


@dataclass
class _ShoulderFeature(_FixedFeature):
    width: float


@dataclass
class _BushingFeature(_FixedFeature):
    width: float
    height: float


@dataclass
class _GearFeature(_FixedFeature):
    gear: Gear


@dataclass
class _BearingFeature(_FixedFeature):
    bearing: Bearing


class PutSide(Enum):
    AFTER = 'after'
    BEFORE = 'before'


@dataclass
class BushingShape:
    length: float
    d2: float
    rise_pos: float = None
    pos_abs: bool = None
    rise_diam: float = None
    rise_length: float = None


def _get_offset(feat, halfl, put_side):
    if isinstance(feat, _StepFeature):
        offset = -halfl
        if put_side == PutSide.AFTER:
            offset = -offset
    elif isinstance(feat, _ShoulderFeature):
        offset = -halfl
        if put_side == PutSide.AFTER:
            offset = -offset + feat.width
    elif isinstance(feat, _StartFeature):
        offset = halfl
    elif isinstance(feat, _EndFeature):
        offset = -halfl
    else:
        # 确定特征宽度
        if isinstance(feat, _BushingFeature):
            feature_width = feat.width / 2
        elif isinstance(feat, _GearFeature):
            feature_width = feat.gear.half_bold
        elif isinstance(feat, _BearingFeature):
            feature_width = feat.bearing.b / 2
        elif isinstance(feat, _CouplingFeature):
            feature_width = feat.length / 2
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

    def _get_chamfer_radius(self, diameter):
        if self is not None and self.cr is not None:
            return self.cr
        for k, v in Shaft.CR_TABLE.items():
            if k[0] < diameter <= k[1]:
                return v
        warnings.warn(f"直径 {diameter} 超出了倒角半径计算的范围。",
                      BadDesignWarning)

    def __init__(self, init_diam):
        self.initial_diameter = init_diam
        self.length = None
        self.steps: list[_StepFeature] = []

        self.cr = None
        self.cr = self._get_chamfer_radius(self.initial_diameter)

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

    def get_ends(self, start=True):
        if start:
            return _StartFeature(0)
        else:
            return _EndFeature(-1)

    def end_at(self, pos, diameter=None):
        self.process_features()
        if pos < self.length:
            raise ValueError
        if diameter is None:
            diameter = self._get_diameter_at(pos, False)
        self.add_step(pos, diameter=diameter)
        return _EndFeature(pos)

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
        if not height > self.cr:
            warnings.warn(
                f"{position} 处的肩部高度 {height} 小于圆角，产生干涉！",
                BadDesignWarning)
        if not height > d * 0.08:
            warnings.warn(
                f"{position} 处的肩部高度 {height} 过低",
                BadDesignWarning)

        self.need_refresh = True  # 需要重新计算轮廓
        self.steps.append(_StepFeature(position, height, False))
        self.steps.append(_StepFeature(position + width, -height, False))
        return _ShoulderFeature(position, width)

    def add_bushing(self, feat, bs: BushingShape,
                    put_side=PutSide.BEFORE, forward=True):
        offset = _get_offset(feat, bs.length / 2, put_side)
        pos = feat.position + offset
        d1 = self._get_diameter_at(pos, False)
        bu = Bushing(d1, bs.d2, bs.length)
        if bs.rise_pos is not None:
            rpos = bs.rise_pos
            if bs.pos_abs:
                rpos = rpos - pos + bs.length / 2
            if rpos is None or bs.rise_diam is None or bs.rise_length is None:
                raise ValueError
            bu.rise = (rpos, bs.rise_diam, bs.rise_length)
        # print(bu.rise)
        # print(bu.d1, bu.d2, bu.length, bu.rise)
        self.bushings.append((pos, bu, forward))
        return _BushingFeature(pos, bs.length, (bs.d2 - d1) / 2)

    def add_keyway(self, feat, length, forward=True):
        if isinstance(feat, _GearFeature):
            pos = feat.position
            bold = feat.gear.half_bold * 2
        elif isinstance(feat, _CouplingFeature):
            pos = feat.position
            bold = feat.length
        else:
            raise ValueError("不支持的特征类型。")
        self.keyways.append((pos, Keyway(
            length, self._get_diameter_at(pos, False)
        ), bold, forward))

    def add_coupling(self, feat, length):
        pos = _get_offset(feat, length / 2, None)
        pos = pos + feat.position
        return _CouplingFeature(pos, length)

    def add_gear(self, pos_or_feat, gear: Gear,
                 forward=True, put_side=PutSide.BEFORE):
        if not isinstance(pos_or_feat, float):
            pos_or_feat = pos_or_feat.position + _get_offset(
                pos_or_feat, gear.half_bold, put_side)
        self.gears.append((pos_or_feat, gear, forward))
        return _GearFeature(pos_or_feat, gear)

    def add_bearing(self, feat, bearing: Bearing,
                    forward=True, put_side=PutSide.BEFORE):
        if not isinstance(feat, (_BushingFeature, _StepFeature)):
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
                 for pos, bu, _ in self.bushings), ())
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
                current_diam += l * 2
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
                fradius = Shaft._get_chamfer_radius(None, min(r0, r1))

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
        path.goto(self.chamfered_contour[0])
        for segment in self.chamfered_contour[1:]:
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
                    if path.points[-1][0] == segment[0]:
                        # print(path.points[-1], segment)
                        drawer.line(path.points[-1],
                                    (segment[0], 0))
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

            for pos, bushing, forward in self.bushings:
                bushing.draw(drawer, (pos, 0),
                             (0, 1) if forward else (0, -1))

            for pos, keyway, bold, forward in self.keyways:
                keyway.draw(
                    drawer, (pos, 0),
                    (-1, 0) if forward else (1, 0), bold)


class BoltHead:
    eA = [3.41, 4.32, 5.45, 6.01, 6.58, 7.66, 8.79, 11.05, 14.38, 17.77,
          20.03, 23.36, 26.75, 30.14, 33.53, 37.72, 39.98, None, None,
          None, None, None, None, None, None, None, None, None, None]
    eB = [3.28, 4.18, 5.31, 5.88, 6.44, 7.5, 8.63, 10.89, 14.2, 17.59, 19.85,
          22.78, 26.17, 29.56, 32.95, 37.29, 39.55, 45.2, 50.85, 55.37, 60.79,
          66.44, 71.3, 76.95, 82.6, 88.25, 93.56, 99.21, 104.86]
    kA = [1.225, 1.525, 1.825, 2.125, 2.525, 2.925, 3.65, 4.15, 5.45,
          6.58, 7.68, 8.98, 10.18, 11.715, 12.715, 14.215, 15.215, None,
          None, None, None, None, None, None, None, None, None, None]
    kB = [1.3, 1.6, 1.9, 2.2, 2.6, 3, 3.74, 4.24, 5.54, 6.69, 7.79,
          9.09, 10.29, 11.85, 12.85, 14.35, 15.35, 17.35, 19.12, 21.42,
          22.92, 25.42, 26.42, 28.42, 30.42, 33.5, 35.5, 38.5]

    @staticmethod
    def get_nominal_parameters(nominal_diameter: int):
        # 公称直径列表（处理后）
        nominal_diameters = [
            'Φ1.6', 'Φ2', 'Φ2.5', 'Φ3', 'Φ4', 'Φ5', 'Φ6', 'Φ8', 'Φ10', 'Φ12',
            'Φ14', 'Φ16', 'Φ18', 'Φ20', 'Φ22', 'Φ24', 'Φ27', 'Φ30', 'Φ33',
            'Φ36', 'Φ39', 'Φ42', 'Φ45', 'Φ48', 'Φ52', 'Φ56', 'Φ60', 'Φ64'
        ]
        # d的最小值列表（公称值）
        d_values = [
            1.7, 2.2, 2.7, 3.2, 4.3, 5.3, 6.4, 8.4, 10.5, 13,
            15, 17, 19, 21, 23, 25, 28, 31, 34, 37, 42, 45, 48,
            52, 56, 62, 66, 70
        ]
        # dc的最大值列表（公称值）
        dc_values = [
            4, 5, 6, 7, 9, 10, 12, 16, 20, 24, 28, 30, 34, 37, 39,
            44, 50, 56, 60, 66, 72, 78, 85, 92, 98, 105, 110, 115
        ]
        # h的公称值列表
        h_values = [
            0.3, 0.3, 0.5, 0.5, 0.8, 1, 1.6, 1.6, 2, 2.5,
            2.5, 3, 3, 3, 3, 4, 4, 4, 5, 5, 6, 8, 8, 8, 8, 10, 10, 10
        ]
        # 创建字典存储数据
        data = {}
        for i, dia in enumerate(nominal_diameters):
            data[dia] = {
                'd': d_values[i],
                'dc': dc_values[i],
                'h': h_values[i]
            }

        # 处理输入的公称直径
        cleaned_input = f'Φ{nominal_diameter}'

        if cleaned_input in data:
            return data[cleaned_input]
        else:
            raise ValueError(f"未找到公称直径为 {nominal_diameter} 的参数")

    # 螺栓直径列表
    bolt_diameters = ["M1.6", "M2", "M2.5", "M3", "(M3.5)", "M4", "M5", "M6", "M8", "M10",
                      "M12", "(M14)", "M16", "(M18)", "M20", "(M22)", "M24", "(M27)", "M30",
                      "(M33)", "M36", "(M39)", "M42", "(M45)", "M48", "(M52)", "M56", "(M60)",
                      "M64"]

    def __init__(self, sz, t='A'):
        # 提取螺栓直径中的数字部分
        self.numeric_diameters = []
        for diameter in self.bolt_diameters:
            # 去除括号和字母 M，然后转换为浮点数
            clean_diameter = diameter.replace(
                "(", "").replace(")", "").replace("M", "")
            self.numeric_diameters.append(float(clean_diameter))

        index = self.numeric_diameters.index(sz)
        self.eA = self.eA[index]
        self.eB = self.eB[index]
        self.kA = self.kA[index]
        self.kB = self.kB[index]

        self.d = sz
        self.e = self.eA if t == 'A' else self.eB
        self.k = self.kA if t == 'A' else self.kB

    def draw(self, drawer: Drawer,
             center: ndarray, direction: ndarray):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center, theta):
            lt = (-self.e / 2, self.k)
            rb = (self.e / 2, 0)
            drawer.wipeout_rect(lt, rb)
            drawer.rect(lt, rb)
            drawer.line((-self.e / 4, 0), (-self.e / 4, self.k))
            drawer.line((self.e / 4, 0), (self.e / 4, self.k))

    def draw_top(self, drawer: Drawer,
                 center: ndarray, direction: ndarray):
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center, theta):
            cir_pts = np.linspace(0, np.pi * 2)
            cir_pts = np.array([np.cos(cir_pts), np.sin(cir_pts)])
            cir_pts = cir_pts.T * self.e
            drawer.wipeout(*cir_pts)
            c = drawer.circle((0, 0), self.e)
            drawer.hexagonal((0, 0), self.e, 0)


class OilPointer:
    def __init__(self, diameter):
        if diameter == 10:
            self.d0 = 16  # 螺纹直径
            self.p0 = 1.5  # 螺距
            self.dc = 22  # 挡盘直径
            self.s = 21  # 六角头尺寸
            self.H = 22
            self.h = 8
        elif diameter == 20:
            self.d0 = 27  # 螺纹直径
            self.p0 = 1.5  # 螺距
            self.dc = 36  # 挡盘直径
            self.s = 32  # 六角头尺寸
            self.H = 30
            self.h = 10
        elif diameter == 32:
            self.d0 = 42  # 螺纹直径
            self.p0 = 1.5  # 螺距
            self.dc = 52  # 挡盘直径
            self.s = 46  # 六角头尺寸
            self.H = 40
            self.h = 12
        else:
            raise ValueError('错误直径')
        self.d = diameter  # 指示器直径
        self.df = self.d0 - 1.22687 * self.p0  # 指示器螺纹内径

    def draw(self, drawer: Drawer,
             center_pos: ndarray,
             direction: ndarray):
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)

        drawer.switch_layer(LayerType.SOLID)
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        with drawer.transformed(center_pos, theta):
            arc1 = drawer.arc3((-self.dc / 2 + 1, self.H / 4),
                               (0, self.H - self.h),
                               (self.dc / 2 - 1, self.H / 4))
            path = Path2D((-self.dc / 2 + 1, self.H / 4))
            path.offset(-1, -1)
            path.goto(-self.dc / 2, 0)
            path.goto(-self.d0 / 2, 0)
            path.offset(0, -self.h + 1)
            path.offset(1, -1)
            path.offset(self.d0 - 2, 0)
            path.offset(1, 1)
            path.offset(0, self.h - 1)
            path.goto(self.dc / 2, 0)
            path.offset(0, self.H / 4 - 1)
            path.offset(-1, 1)
            outer = path.draw(drawer)
            ipath = Path2D((-self.d / 2, self.H / 3))
            ipath.goto(-self.d / 2, -self.h)
            ipath.goto(self.d / 2, -self.h)
            ipath.goto(self.d / 2, self.H / 3)
            inner = ipath.draw(drawer)
            arc2 = drawer.arc((0, self.H / 3), self.d / 2,
                              0, 180)
            drawer.hatch([outer, arc1], inner_objs=[[arc2, inner]],
                         hatch_type=HatchType.GLASS)
            arc1.Delete()
            outer.Delete()
            arc2.Delete()
            inner.Delete()
            drawer.arc3((-self.dc / 2 + 1, self.H / 4),
                        (0, self.H - self.h),
                        (self.dc / 2 - 1, self.H / 4))
            path.draw(drawer)
            ipath.draw(drawer)
            drawer.arc((0, self.H / 3), self.d / 2,
                       0, 180)
            drawer.line((-self.d0 / 2, 0), (-self.df / 2, 0))
            drawer.line((self.d0 / 2, 0), (self.df / 2, 0))
            lt = (-self.dc / 2, 0)
            rb = (-self.d0 / 2, -1)
            drawer.hatch(drawer.rect(lt, rb), hatch_type=HatchType.SOLID)
            lt = (self.dc / 2, 0)
            rb = (self.d0 / 2, -1)
            drawer.hatch(drawer.rect(lt, rb), hatch_type=HatchType.SOLID)
            drawer.switch_layer(LayerType.THIN)
            drawer.line((-self.df / 2, 0), (-self.df / 2, -self.h))
            drawer.line((self.df / 2, 0), (self.df / 2, -self.h))


class ViewPort(Enum):
    TOP2BOTTOM = 1
    LEFT2RIGHT = 2


class Box:
    FOOT_BOLT = {
        'a': ((100, 150, 200, 250, 300, 350, 400, 450,
               500, 600, 700, 800, 900, 1000),
              (250, 350, 425, 500, 600, 650, 750, 850,
               1000, 1150, 1300, 1500, 1700, 2000),
              (500, 650, 750, 825, 950, 1100, 1250,
               1450, 1650, 1900, 2150)),
        'size': ((16, 16, 16, 20, 24, 24, 30, 30, 36, 36, 42, 42, 48, 48),
                 (20, 20, 20, 24, 24, 30, 30, 36, 36, 42, 42, 48, 48, 56),
                 (20, 24, 24, 30, 30, 36, 36, 42, 42, 48, 48)),
        'n': ((4, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,),
              (6, 6, 6, 8, 8, 8, 8, 8, 8, 8, 8, 10, 10, 10),
              (8, 8, 10, 10, 10, 10, 10, 10, 10, 10, 10))
    }

    @staticmethod
    def _get_bolt_flange(d: int, is_feet: bool):
        if is_feet:
            # 螺栓孔凸缘的配置尺寸
            ind = [6, 8, 10, 12, 16, 20, 22, 24, 27, 30]
            C1 = [12, 15, 18, 2, 26, 30, 36, 36, 40, 42]
            C2 = [10, 13, 14, 18, 21, 26, 30, 30, 34, 36]
            D0 = [15, 20, 25, 30, 40, 45, 48, 48, 55, 60]
            rmax = [3, 3, 4, 4, 5, 5, 8, 8, 8, 8]
        else:
            # 地脚螺栓孔凸缘的配置尺寸
            ind = [16, 20, 22, 24, 27, 30, 36, 42, 48, 56]
            C1 = [25, 30, 35, 50, 55, 60, 70, 95]
            C2 = [22, 25, 30, 50, 58, 60, 70, 95]
            D0 = [45, 48, 60, 85, 100, 110, 130, 170]
            rmax = [np.inf for i in range(len(ind))]
        val = min(ind, key=lambda x: abs(x - d))
        ind = ind.index(val)
        return C1[ind], C2[ind], D0[ind], rmax[ind]

    B1_SCALE: tuple = (0.8, 0.85)
    H0_SCALE: tuple = (1.5, 1.75)
    H1_SCALE: tuple = (1.5, 1.75)
    H2_SCALE: tuple = (1.5, 1.75)
    H4_SCALE: tuple = (1.75, 2)
    H5_SCALE: tuple = (2, 3)
    E_SCALE: tuple = (0.8, 0.1)
    E1_SCALE: tuple = (0.8, 0.85)
    D_SCALE: tuple = (1.5, 2)
    D3_SCALE: tuple = (0.5, 0.6)
    D5_SCALE: tuple = (0.3, 0.4)
    H_PLUS_SCALE: tuple = (30, 50)
    L1_PLUS_SCALE: tuple = (5, 10)

    def _calc_all_scales(self):
        scale = self.scale
        for attr in Box.__annotations__:
            if attr.endswith("_SCALE"):
                min_scale, max_scale = getattr(self, attr)
                setattr(self, attr, min_scale +
                        (max_scale - min_scale) * scale)

    def _calc_cover_l1(self, c1, c2):
        '''箱体和箱盖凸缘宽度计算'''
        return round(c1 + c2 + self.L1_PLUS_SCALE)

    def __init__(self, gears, bearings, scale=0.5):
        if not 0 <= scale <= 1:
            raise ValueError("比例系数必须在 0 到 1 之间。")
        self.scale = scale
        self._calc_all_scales()

        self.gears: list[Gear] = gears
        self.bearings: list[Bearing] = bearings
        self.aI = self.gears[0].r + self.gears[1].r  # 高速级中心距
        self.aII = self.gears[3].r + self.gears[2].r  # 低速级中心距
        Ds = [b.da for b in self.bearings]  # 轴承外径

        self.b = round(max(0.025 * self.aII + 3, 8))  # 底座壁厚δ
        self.b1 = round(max(self.b * self.B1_SCALE, 8))  # 箱体壁厚δ₁
        self.h0 = round(self.b * self.H0_SCALE)  # 底座上部凸缘厚度h₀
        self.h1 = round(self.b1 * self.H1_SCALE)  # 箱盖凸缘厚度h₁
        self.h2 = round(self.b * self.H2_SCALE)  # 底座下部凸缘厚度h₂、h₃、h₄
        self.h3 = round(self.b * 1.5)  # 底座下部凸缘厚度h₂、h₃、h₄
        self.h4 = round(self.h3 * self.H4_SCALE)  # 底座下部凸缘厚度h₂、h₃、h₄
        self.h6 = None  # 吊环螺栓座凸缘高度h₆
        self.e = round(self.b * self.E_SCALE)  # 底座加强筋厚度e
        self.e1 = round(self.b * self.E1_SCALE)  # 箱盖加强筋厚度e₁
        if self.aII in Box.FOOT_BOLT['a'][1]:
            idx = Box.FOOT_BOLT['a'][1].index(self.aII)
        else:
            d_feet = self.b * self.D_SCALE
            most_close = min(Box.FOOT_BOLT['size']
                             [1], key=lambda x: abs(x - d_feet))
            idx = Box.FOOT_BOLT['size'][1].index(most_close)
        self.n_feet = Box.FOOT_BOLT['n'][1][idx]  # 地脚螺栓数目nf
        if self.n_feet != 6:
            raise NotImplementedError
        self.d_feet = Box.FOOT_BOLT['size'][1][idx]  # 地脚螺栓直径d
        self.d2 = round(self.d_feet * 0.75)  # 轴承座连接螺栓直径d₂
        self.h5 = round(self.d2 * 2 * self.H5_SCALE)  # 轴承座连接螺栓凸缘厚度h₅
        self.d3 = round(self.d_feet * self.D3_SCALE)  # 底座与箱盖连接螺栓直径d₃
        self.d5 = round(self.d_feet * self.D5_SCALE)  # 视孔盖固定螺栓直径d₅
        self.d6 = round(0.8 * self.d_feet)  # 吊环螺栓直径d₈

        # 铸造壁相交部分的尺寸
        if 10 <= self.b < 15:
            self.X, self.Y, self.R = 3, 15, 5
        elif 15 <= self.b < 20:
            self.X, self.Y, self.R = 4, 20, 5
        elif 20 <= self.b < 25:
            self.X, self.Y, self.R = 5, 25, 5
        elif 25 <= self.b < 30:
            self.X, self.Y, self.R = 6, 30, 8
        elif 30 <= self.b <= 35:
            self.X, self.Y, self.R = 7, 35, 10  # R >= 8 可
        else:
            warnings.warn(f"壁厚 {self.b} 超出了给定的范围",
                          BadDesignWarning)
            if self.b <= 0:
                self.X, self.Y, self.R = 3, 15, 5
            else:
                self.X, self.Y, self.R = 7, 35, 12

        # 箱体内壁和齿顶的间隙
        self.delta = round(self.b * 1.2 + 0.5)
        self.delta1 = 15  # 箱体内壁与齿轮端面的间隙
        # 底座深度
        self.H = round(self.gears[1].ra + self.H_PLUS_SCALE)
        self.H1 = max(self.aI, self.aII)  # 底座高度

        # 其他圆角半径
        self.r1 = round(0.25 * self.h3)
        self.r2 = self.h3

        g1, g2 = self.gears[0], self.gears[-1]
        self.length = self.aI + self.aII + g1.ra + g2.ra + self.delta * 2
        width = sum(map(lambda g: g.half_bold, self.gears))
        self.width = self.delta1 * 3 + width

        self.c1, self.c2 = self._get_bolt_flange(self.d3, False)[:2]
        self.l1 = self._calc_cover_l1(self.c1, self.c2)
        self.B = self.l1 + self.b
        c1, c2, _, _ = self._get_bolt_flange(self.d_feet, True)
        self.c11, self.c21 = c1, c2

        self.oil_pointer: OilPointer = None
        self.shafts: list[Shaft] = [None, None, None]
        self.syoffs: list[float] = [None, None, None]
        self.bearing_covers: list[list[
            BearingCover]] = [[], [], []]

    def accept(self, obj):
        if isinstance(obj, OilPointer):
            self.oil_pointer = obj
        else:
            raise TypeError('未知物品')

    def gen_shaft1(self, d, m=40):
        shaft1 = Shaft(d)
        dd = round(0.07 * d + 1)
        b1 = self.bearings[0]
        d2 = round(b1.d + 2 * b1.inner_thick / 3)
        bc1 = BearingCover(b1.da, d + dd * 2, m, True)
        
        pos1 = 38 + 10
        pos2 = pos1 + bc1.e
        pos3 = pos2 + 20
        pos4 = pos3 + b1.b
        pos4_5 = pos2 + self.B
        pos5 = pos4_5 + 10
        # print(pos2, pos4_5)
        L = 410
        m2 = 435 - L + bc1.e
        bc12 = BearingCover(b1.da, b1.d, m2, False)
        pos11 = L
        pos10 = pos11 - b1.b
        pos9 = pos11 + m2 - self.B
        pos8 = pos9 - self.delta1
        pos7 = pos8 - self.gears[0].half_bold * 2
        pos6 = pos7 - 10
        # print(m2, pos8, pos9, pos10, pos11, L)
        
        shaft1.add_step(38, diameter=bc1.d1)
        shaft1.add_step(pos3, diameter=b1.d)
        st = shaft1.add_step(pos5, dd)
        sh = shaft1.add_shoulder(pos6, 10, 10)
        g = shaft1.add_gear(
            sh, self.gears[0], put_side=PutSide.AFTER)
        shaft1.add_keyway(g, 40)
        shaft1.add_step(pos8 - 2, -dd)
        shaft1.add_step(pos11 - 1, 0)
        
        bu1 = shaft1.add_bushing(st, BushingShape(
            pos5 - pos4, b1.d + dd * 2, pos4_5 - 5,
            True, bc1.D, 5
        ), PutSide.BEFORE)
        shaft1.add_bearing(bu1, b1, False)
        
        bu2 = shaft1.add_bushing(g, BushingShape(
            pos9 - pos8 - 3, b1.d + dd * 2,
            pos8, True, bc1.D,
            5
        ), PutSide.AFTER)
        bu3 = shaft1.add_bushing(bu2, BushingShape(
            pos10 - pos9 + 3, b1.d + dd * 2, pos9 - 2,
            True, bc1.D, 5
        ), PutSide.AFTER)
        shaft1.add_bearing(bu3, b1, True, PutSide.AFTER)
        
        self.shafts[0] = shaft1
        self.bearing_covers[0] = (bc1, bc12)
        self.syoffs[0] = -(38 + 10 + bc1.e)
        return shaft1

    def gen_shaft2(self, d, m=30):
        shaft2 = Shaft(d)
        dd = round(0.07 * d + 1)
        b2 = self.bearings[1]
        d2 = round(b2.d + b2.inner_thick)
        bc2 = BearingCover(b2.da, b2.d, m)
        print(b2.d)
        
        g2 = self.gears[1]
        g3 = self.gears[2]
        lenbu = 20
        pos0 = -bc2.m
        pos2 = pos0 + self.B
        pos3 = pos2 + self.delta1
        pos4 = pos3 + g3.half_bold * 2
        pos5 = pos4 + self.delta1 + g2.half_bold * 2
        pos6 = pos5 + self.delta1
        pos7 = pos5 + lenbu
        
        shaft2.add_step(pos3 + 2, diameter=g3.r_hole * 2)
        s1 = shaft2.add_step(pos4, 10)
        s2 = shaft2.add_step(pos4 + self.delta1 - 3, diameter=g2.r_hole * 2)
        shaft2.add_step(pos5 - 2, diameter=b2.d)
        shaft2.add_step(pos7 + b2.b - 1, 0)
        g2 = shaft2.add_gear(s2, g2, put_side=PutSide.AFTER)
        g3 = shaft2.add_gear(s1, g3, put_side=PutSide.BEFORE)
        shaft2.add_keyway(g2, 50)
        shaft2.add_keyway(g3, 50)
        
        bu1 = shaft2.add_bushing(g3, BushingShape(
            (pos3 - b2.b) / 3, d2, pos3 - 5,
            True, bc2.D, 5
        ))
        bu12 = shaft2.add_bushing(bu1, BushingShape(
            (pos3 - b2.b) / 3 * 2, d2, pos2 - 2,
            True, bc2.D, 5
        ))
        bu2 = shaft2.add_bushing(g2, BushingShape(
            (pos7 - pos5) / 2 + 1, d2, pos5 - 3,
            True, g2.gear.r_hole * 2 + 4, 5
        ), PutSide.AFTER, True)
        bu3 = shaft2.add_bushing(bu2, BushingShape(
            (pos7 - pos5) / 2 + 2, d2, pos6 - 2,
            True, bc2.D, 5
        ), PutSide.AFTER, True)
        shaft2.add_bearing(bu12, b2, False)
        shaft2.add_bearing(bu3, b2, put_side=PutSide.AFTER)
        m2 = self.B * 2 + self.width - m - pos7 - b2.b
        print(pos5)
        bc21 = BearingCover(b2.da, b2.d, m2)
        
        self.shafts[1] = shaft2
        self.bearing_covers[1] = (bc2, bc21)
        self.syoffs[1] = bc2.m
        return shaft2

    def gen_shaft3(self, d, m=40):
        shaft3 = Shaft(d)
        dd = round(0.07 * d + 1)
        b3 = self.bearings[2]
        d2 = round(b3.d + 2 * b3.inner_thick / 3)
        bc3 = BearingCover(b3.da, b3.d, m)
        
        g = self.gears[-1]
        pos1 = -m + self.B
        pos2 = pos1 + 20
        pos3 = self.delta1 + pos1
        pos4 = pos3 + g.half_bold * 2
        pos6 = -m + self.B + self.width
        pos5 = pos6 - 20
        m2 = 30
        bc31 = BearingCover(b3.da, b3.d, m2, True)
        pos7 = pos6 + self.B - m2 - b3.b
        pos8 = pos6 + b3.b
        pos9 = pos8 + m2 + bc31.e + 10
    
        shaft3.add_step(pos3 + 2, diameter=g.r_hole * 2)
        s1 = shaft3.add_step(pos4, 10)
        shaft3.add_step(pos4 + self.delta1, diameter=g.r_hole * 2 + 5)
        st = shaft3.add_step(pos5, diameter=bc31.d1)
        shaft3.add_step(pos8, diameter=bc31.d0)
        shaft3.add_step(pos9, diameter=d)
        shaft3.add_step(pos9 + 82, 0)
        g = shaft3.add_gear(s1, g, put_side=PutSide.BEFORE)
        shaft3.add_keyway(g, 63)

        bu1 = shaft3.add_bushing(g, BushingShape(
            pos3 - pos2, b3.d + dd * 2, pos3 - 5,
            True, bc3.D, 5
        ), PutSide.BEFORE)
        bu2 = shaft3.add_bushing(bu1, BushingShape(
            pos2 - b3.b, b3.d + dd * 2, pos1 - 2,
            True, bc3.D, 5
        ), PutSide.BEFORE)
        shaft3.add_bearing(bu2, b3, False)
        
        bu3 = shaft3.add_bushing(st, BushingShape(
            pos7 - pos5, b3.d + dd * 2, pos6 - 2,
            True, bc3.D, 5
        ), PutSide.AFTER)
        shaft3.add_bearing(bu3, b3, put_side=PutSide.AFTER)

        self.shafts[2] = shaft3
        self.bearing_covers[2] = (bc3, bc31)
        self.syoffs[2] = m
        return shaft3

    def _draw_bottom_layer0_half(self, drawer: Drawer):
        halfl = self.length / 2
        dc = BoltHead.get_nominal_parameters(self.d_feet)
        dc = dc['dc']
        # C1 内侧， C2 外侧
        c1, c2 = self.c11, self.c21
        yoff = self.width / 2 + c1 + c2 + self.b
        with drawer.transformed((0, -yoff)):
            drawer.line((halfl, c1 + c2 + c2),
                        (halfl, c2))
            drawer.arc((halfl - c2, c2 * 2 + c1), c2,
                       0, -90)
            drawer.arc((halfl - c2, c2), c2,
                       0, -90)
            drawer.line((halfl - c2, 0), (0, 0))
            drawer.circle((halfl - dc, c2), dc / 2)
            drawer.circle((halfl - dc, c2), self.d_feet / 2)
            drawer.arc((0, c2), dc / 2,
                       -90, 90)
            drawer.arc((0, c2), self.d_feet / 2,
                       -90, 90)

            with drawer.transformed((halfl / 2, (c1 + c2) / 2)):
                xoff, yoff = self.e / 2, (c1 + c2) / 2 - self.r1
                path = Path2D((-xoff, yoff))
                path.offset(0, -yoff)
                path.offset(xoff * 2, 0)
                path.offset(0, yoff)
                path.draw(drawer)
                drawer.arc((xoff + self.r1, yoff), self.r1,
                           180, 90)
                drawer.arc((-xoff - self.r1, yoff), self.r1,
                           0, 90)
                yoff = yoff + self.r1
                drawer.line((-halfl / 2, yoff), (-xoff - self.r1, yoff))
                drawer.line((halfl / 2 - c2, yoff), (xoff + self.r1, yoff))

    def _draw_bottom_layer0(self, drawer: Drawer):
        self._draw_bottom_layer0_half(drawer)
        with drawer.transformed(mirrored_axis='y'):
            self._draw_bottom_layer0_half(drawer)
        if self.oil_pointer is not None:
            with drawer.transformed((-self.length / 2 + self.b, 0)):
                l = self.oil_pointer.dc * 2
                path = Path2D((0, 0))
                path.offset(0, l)
                path.offset(l, 0)
                path.offset(0, -l)
                path.draw(drawer)

    def _draw_bottom_layer1(self, drawer: Drawer):
        g1, g2, g3, g4 = self.gears
        bc1, bc2, bc3 = self.bearing_covers

        path = Path2D((-self.length / 2 - self.l1, 0))
        path.offset(0, -self.width / 2)
        path.arc(self.l1, 90)
        pt1 = np.array((
            -self.length / 2 + self.delta + g1.ra,
            -self.width / 2 - self.l1
        ))
        path.goto(pt1 - (bc1[0].D2 / 2 + self.b1, 0) - (self.b1, 0))
        path.arc(1, 90, False)
        path.arc(self.b1 - 1, 90, tang=(0, -1))
        path.offset(self.b1 / 2, 0)
        pt_s1 = path.offset(bc1[0].D2, 0)
        pt_s1 = pt_s1 - (bc1[0].D2 / 2, 0)
        path.offset(self.b1 / 2, 0)
        path.arc(self.b1 - 1, 90)
        path.arc(1, 90, False, (0, 1))
        # print(path.points)

        path.offset(self.aI - bc2[0].D2 / 2 - bc1[0].D2 / 2 - self.b1 * 3, 0)
        path.arc(1, 90, False)
        path.arc(self.b1 - 1, 90, tang=(0, -1))
        path.offset(self.b1 / 2, 0)
        pt_s2 = path.offset(bc2[0].D2, 0)
        pt_s2 = pt_s2 - (bc2[0].D2 / 2, 0)
        path.offset(self.b1 / 2, 0)
        path.arc(self.b1 - 1, 90)
        path.arc(1, 90, False, (0, 1))

        path.offset(self.aII - bc3[0].D2 / 2 - bc2[0].D2 / 2 - self.b1 * 3, 0)
        path.arc(1, 90, False)
        path.arc(self.b1 - 1, 90, tang=(0, -1))
        path.offset(self.b1 / 2, 0)
        pt_s3 = path.offset(bc3[0].D2, 0)
        pt_s3 = pt_s3 - (bc3[0].D2 / 2, 0)
        path.offset(self.b1 / 2, 0)
        path.arc(self.b1 - 1, 90)
        path.arc(1, 90, False, (0, 1))

        path.goto(self.length / 2, -self.width / 2 - self.l1)
        path.arc(self.l1, 90)

        path.goto(self.length / 2 + self.l1, 0)

        path.goto(-self.length / 2 - self.l1, 0)
        path.wipeout(drawer)
        with drawer.transformed(mirrored_axis='x'):
            path.wipeout(drawer)
        path.points.pop()
        path.draw(drawer)
        with drawer.transformed(mirrored_axis='x'):
            path.draw(drawer)

        path = Path2D((-self.length / 2, 0))
        path.offset(0, -self.width / 2 + self.c2)
        path.arc(self.c2, 90)
        path.offset(self.length - self.c2 * 2, 0)
        path.arc(self.c2, 90)
        path.offset(0, self.width / 2 - self.c2)
        path.draw(drawer)
        with drawer.transformed(mirrored_axis='x'):
            path.draw(drawer)

        def draw_doubleline(pos, width, len):
            pt1 = np.array((pos[0] - width / 2, 0))
            pt2 = np.array((pos[0] + width / 2, 0))
            drawer.line(pt1, pt1 + (0, len))
            drawer.line(pt2, pt2 + (0, len))

        pt_ss = [pt_s1, pt_s2, pt_s3]
        for pt_s, bc in zip(pt_ss, [bc1[0], bc2[0], bc3[0]]):
            with drawer.transformed(pt_s):
                bc.draw(drawer, (0, 0), (0, -1))
                drawer.switch_layer(LayerType.SOLID)
                draw_doubleline((0, 0), bc.D, self.B)
        with drawer.transformed(mirrored_axis='x'):
            for pt_s, bc in zip(pt_ss, [bc1[1], bc2[1], bc3[1]]):
                with drawer.transformed(pt_s):
                    bc.draw(drawer, (0, 0), (0, -1))
                    drawer.switch_layer(LayerType.SOLID)
                    draw_doubleline((0, 0), bc.D, self.B)

        pt_s1  = pt_s1 + (0, self.syoffs[0])
        pt_s2  = pt_s2 + (0, self.syoffs[1])
        pt_s3  = pt_s3 + (0, self.syoffs[2])
        self.shafts[0].draw(drawer, pt_s1, (0, -1))
        self.shafts[1].draw(drawer, pt_s2, (0, -1))
        self.shafts[2].draw(drawer, pt_s3, (0, -1))

    def draw(self, drawer: Drawer, view: ViewPort,
             center: ndarray, dire: ndarray):
        theta = np.arctan2(dire[1], dire[0]) - np.pi / 2
        if view == ViewPort.TOP2BOTTOM:
            with drawer.transformed(center, theta):
                drawer.switch_layer(LayerType.SOLID)
                self._draw_bottom_layer0(drawer)
                with drawer.transformed(mirrored_axis='x'):
                    drawer.switch_layer(LayerType.SOLID)
                    self._draw_bottom_layer0(drawer)
            with drawer.transformed(center, theta):
                drawer.switch_layer(LayerType.SOLID)
                self._draw_bottom_layer1(drawer)
